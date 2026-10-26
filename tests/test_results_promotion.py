from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import translation

from apps.academics.models import (
    CourseType,
    GradeScale,
    Outcome,
    PromotionDecision,
    PromotionOverride,
    PromotionRule,
    Result,
    RetakePolicy,
)
from apps.academics.selectors import get_current_courses
from apps.academics.services import gpa, importers, promotion, results
from apps.academics.services.promotion import RuleSnapshot, StalePreview, decide
from apps.accounts.models import AcademicStatus
from apps.auditlog.models import AuditEvent
from apps.enrollment.models import Enrollment, EnrollmentStatus
from apps.enrollment.services import enrollments
from tests.factories import (
    DepartmentFactory,
    LevelTermFactory,
    ProgramFactory,
    claim,
    make_admin,
    make_hod,
    make_student,
    make_teacher,
    sign_in,
)
from tests.test_academics import make_course, make_offering, make_semester

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _english():
    with translation.override("en"):
        yield


@pytest.fixture
def admin(db):
    return make_admin()


@pytest.fixture
def admin_client(client, admin):
    client.defaults["HTTP_ACCEPT_LANGUAGE"] = "en"
    sign_in(client, admin)
    return client


def grade(letter: str) -> GradeScale:
    return GradeScale.objects.get(letter=letter)


def attempt(course, letter, *, semester=1, credit="3", enrollment=None):
    points = grade(letter).points
    return gpa.Attempt(
        course_id=course,
        semester_id=semester,
        semester_start=date(2026, semester, 1),
        enrollment_id=enrollment or semester * 100 + course,
        credit=Decimal(credit),
        points=points,
        passed=letter != "F",
    )


class World:
    """One program with two levels/terms (the second is its last), a current semester S1
    with the first level/term's offerings and a next semester S2 with offerings of the second
    level/term plus C101 again (for retakes). C102 and C103 are not offered in S2."""

    def __init__(self, *, next_offerings=True):
        self.department = DepartmentFactory(code="CSE")
        self.program = ProgramFactory(department=self.department, code="BSC")
        self.l1, self.l2 = LevelTermFactory(name="L1T1"), LevelTermFactory(name="L1T2")
        self.s1 = make_semester(
            "S1", current=True, start_date=date(2026, 1, 1), end_date=date(2026, 6, 30)
        )
        self.s2 = make_semester("S2", start_date=date(2026, 7, 1), end_date=date(2026, 12, 31))
        self.teacher = make_teacher(self.department)
        course = self.course
        self.c101, self.c102 = course("C101", self.l1), course("C102", self.l1)
        self.c103 = course("C103", self.l1, credit=Decimal("1.5"), course_type=CourseType.LAB)
        self.c201, self.c202 = course("C201", self.l2), course("C202", self.l2)
        self.o101, self.o102, self.o103 = (
            self.offer(c, self.s1) for c in (self.c101, self.c102, self.c103)
        )
        self.next = {}
        if next_offerings:
            self.next = {c.code: self.offer(c, self.s2) for c in (self.c101, self.c201, self.c202)}

    def course(self, code, level_term, credit=3, **fields):
        return make_course(
            self.department,
            code,
            level_term=level_term,
            program=self.program,
            credit=credit,
            **fields,
        )

    def offer(self, course, semester, section=""):
        return make_offering(course, semester, self.teacher, section=section)

    def student(self, level_term=None, section=""):
        student = make_student(self.department)
        student.program, student.level_term, student.section = (
            self.program,
            level_term or self.l1,
            section,
        )
        student.save()
        return student

    def graded(self, letters, *, published=True, level_term=None, offerings=None):
        """A student with one result per S1 offering: ``letters`` like ``"A+ A B"``."""
        student = self.student(level_term)
        for offering, letter in zip(
            offerings or (self.o101, self.o102, self.o103), letters.split(), strict=True
        ):
            add_result(student, offering, letter, published=published)
        return student


def add_result(student, offering, letter, *, published=True, status=EnrollmentStatus.REGULAR):
    enrollment = Enrollment.objects.create(
        student_profile=student, offering=offering, status=status
    )
    chosen = grade(letter)
    return Result.objects.create(
        enrollment=enrollment, grade=chosen, points=chosen.points, published=published
    )


@pytest.fixture
def world():
    return World()


def decision_of(planned, student):
    return next(d for d in planned.decisions if d.student_profile_id == student.pk)


def new_enrollments(student, semester):
    return set(
        Enrollment.objects.filter(student_profile=student, offering__semester=semester).values_list(
            "offering_id", "status"
        )
    )


class TestGradeScale:
    def test_default_scale_is_the_ugc_4_point_scale(self):
        assert [(g.letter, str(g.points), g.is_pass) for g in GradeScale.objects.all()] == [
            ("A+", "4.00", True),
            ("A", "3.75", True),
            ("A-", "3.50", True),
            ("B+", "3.25", True),
            ("B", "3.00", True),
            ("B-", "2.75", True),
            ("C+", "2.50", True),
            ("C", "2.25", True),
            ("D", "2.00", True),
            ("F", "0.00", False),
        ]

    def test_default_rule(self):
        rule = PromotionRule.current()
        assert (rule.pk, rule.max_failed_courses, rule.min_cgpa, rule.min_credits) == (
            1,
            2,
            Decimal("2.00"),
            Decimal("0"),
        )
        assert rule.retake_policy == RetakePolicy.LATEST
        assert PromotionRule.current().pk == 1
        assert PromotionRule.objects.count() == 1


class TestGpaArithmetic:
    def test_credit_weighted_term_gpa(self):
        # 3 x 4.00 + 3 x 3.00 + 1.5 x 0.00 = 21 over 7.5 credits
        attempts = [attempt(1, "A+"), attempt(2, "B"), attempt(3, "F", credit="1.5")]
        assert gpa.term_gpa(attempts, 1) == Decimal("2.80")

    def test_rounds_half_up_to_two_places(self):
        # (3.75 + 3.50) / 2 = 3.625 -> 3.63 (bankers' rounding would give 3.62)
        assert gpa.weighted([attempt(1, "A", credit="1"), attempt(2, "A-", credit="1")]) == Decimal(
            "3.63"
        )
        # (3 x 3.75 + 1.5 x 3.25) / 4.5 = 3.5833...
        assert gpa.weighted([attempt(1, "A"), attempt(2, "B+", credit="1.5")]) == Decimal("3.58")

    def test_no_credits_means_no_gpa(self):
        assert gpa.weighted([]) is None
        assert gpa.term_gpa([attempt(1, "A")], 2) is None

    def test_cgpa_counts_the_latest_attempt_of_a_retaken_course(self):
        attempts = [
            attempt(1, "F", semester=1),
            attempt(2, "A+", semester=1),
            attempt(1, "B", semester=2),
        ]
        assert gpa.term_gpa(attempts, 1) == Decimal("2.00")
        assert gpa.term_gpa(attempts, 2) == Decimal("3.00")
        # course 1 counts once, with its retake: (3 x 3.00 + 3 x 4.00) / 6
        assert gpa.cgpa(attempts, RetakePolicy.LATEST) == Decimal("3.50")
        assert gpa.failed_courses(attempts, RetakePolicy.LATEST) == ()

    def test_latest_and_best_policies_differ_when_a_retake_is_worse(self):
        attempts = [attempt(1, "B", semester=1), attempt(1, "C+", semester=2)]
        assert gpa.cgpa(attempts, RetakePolicy.LATEST) == Decimal("2.50")
        assert gpa.cgpa(attempts, RetakePolicy.BEST) == Decimal("3.00")

    def test_failing_again_keeps_the_course_failed(self):
        attempts = [attempt(1, "F", semester=1), attempt(1, "F", semester=2), attempt(2, "D")]
        assert gpa.failed_courses(attempts, RetakePolicy.LATEST) == (1,)
        assert gpa.failed_courses(attempts, RetakePolicy.BEST) == (1,)

    def test_load_attempts_skips_unpublished_and_later_semesters(self, world):
        student = world.graded("A+ A B")
        Result.objects.filter(enrollment__offering=world.o103).update(published=False)
        add_result(student, world.next["C201"], "A")
        found = gpa.load_attempts([student.pk], world.s1)[student.pk]
        assert sorted(a.course_id for a in found) == [world.c101.pk, world.c102.pk]
        later = gpa.load_attempts([student.pk], world.s2)[student.pk]
        assert sorted(a.course_id for a in later) == [world.c101.pk, world.c102.pk, world.c201.pk]


RULE = RuleSnapshot(
    max_failed_courses=2, min_cgpa=Decimal("2.00"), min_credits=Decimal("6"), retake_policy="latest"
)


def rule_says(failed=0, cgpa="3.00", credits="6", last=False):
    return decide(RULE, failed=failed, cgpa=Decimal(cgpa), credits=Decimal(credits), last=last)


class TestRuleBoundaries:
    def test_clean_pass_promotes(self):
        assert rule_says() == Outcome.PROMOTE

    def test_failed_courses_up_to_the_limit_promote_with_retakes(self):
        assert rule_says(failed=1) == Outcome.PROMOTE_WITH_RETAKES
        assert rule_says(failed=2) == Outcome.PROMOTE_WITH_RETAKES
        assert rule_says(failed=3) == Outcome.RETAIN

    def test_cgpa_exactly_at_the_minimum_is_enough(self):
        assert rule_says(cgpa="2.00") == Outcome.PROMOTE
        assert rule_says(cgpa="1.99") == Outcome.RETAIN

    def test_credits_exactly_at_the_minimum_are_enough(self):
        assert rule_says(credits="6") == Outcome.PROMOTE
        assert rule_says(credits="5.5") == Outcome.RETAIN

    def test_last_level_term_graduates_only_with_nothing_to_retake(self):
        assert rule_says(last=True) == Outcome.GRADUATE
        assert rule_says(failed=1, last=True) == Outcome.RETAIN
        assert rule_says(cgpa="1.99", last=True) == Outcome.RETAIN


class TestPreview:
    def test_known_students(self, world):
        good = world.graded("A+ A B")
        retake = world.graded("F B A+")
        weak = world.graded("F F F")
        planned = promotion.preview(world.s1)
        assert [d.student_profile_id for d in planned.decisions] == [good.pk, retake.pk, weak.pk]

        first = decision_of(planned, good)
        # (3 x 4.00 + 3 x 3.75 + 1.5 x 3.00) / 7.5
        assert (first.term_gpa, first.cgpa, first.credits_earned) == (
            Decimal("3.70"),
            Decimal("3.70"),
            Decimal("7.5"),
        )
        assert first.outcome == first.computed == Outcome.PROMOTE
        assert first.to_level_term_id == world.l2.pk
        assert first.enrollments == tuple(
            promotion.PlannedEnrollment(world.next[code].pk, EnrollmentStatus.REGULAR)
            for code in ("C201", "C202")
        )

        second = decision_of(planned, retake)
        # (0 + 9 + 6) / 7.5 = 2.00: exactly the minimum CGPA
        assert second.cgpa == Decimal("2.00")
        assert second.outcome == Outcome.PROMOTE_WITH_RETAKES
        assert second.failed_course_ids == (world.c101.pk,)
        assert second.credits_earned == Decimal("4.5")
        assert {(e.offering_id, e.status) for e in second.enrollments} == {
            (world.next["C101"].pk, EnrollmentStatus.RETAKE),
            (world.next["C201"].pk, EnrollmentStatus.REGULAR),
            (world.next["C202"].pk, EnrollmentStatus.REGULAR),
        }

        third = decision_of(planned, weak)
        assert third.outcome == Outcome.RETAIN
        assert third.to_level_term_id == world.l1.pk
        assert third.enrollments == (
            promotion.PlannedEnrollment(world.next["C101"].pk, EnrollmentStatus.RETAKE),
        )
        assert third.unplaced_course_ids == (world.c102.pk, world.c103.pk)

    def test_students_with_a_missing_or_unpublished_result_wait(self, world):
        unpublished = world.graded("A A A", published=False)
        missing = world.student()
        add_result(missing, world.o101, "A")
        Enrollment.objects.create(student_profile=missing, offering=world.o102)
        planned = promotion.preview(world.s1)
        assert planned.decisions == ()
        assert planned.pending_ids == (unpublished.pk, missing.pk)

    def test_inactive_students_are_left_out(self, world):
        dropped = world.graded("A A A")
        dropped.academic_status = AcademicStatus.DROPPED
        dropped.save()
        assert promotion.preview(world.s1).decisions == ()

    def test_retake_prefers_the_students_section(self, world):
        b_section = world.offer(world.c102, world.s2, section="B")
        a_section = world.offer(world.c102, world.s2, section="A")
        student = world.student(section="A")
        for offering, letter in ((world.o101, "A"), (world.o102, "F"), (world.o103, "A")):
            add_result(student, offering, letter)
        planned = decision_of(promotion.preview(world.s1), student)
        assert (a_section.pk, EnrollmentStatus.RETAKE) in {
            (e.offering_id, e.status) for e in planned.enrollments
        }
        assert b_section.pk not in {e.offering_id for e in planned.enrollments}

    def test_no_next_semester_means_no_enrollments(self):
        world = World(next_offerings=False)
        world.s2.delete()
        student = world.graded("F A A")
        planned = promotion.preview(world.s1)
        assert planned.target_semester_id is None
        only = decision_of(planned, student)
        assert only.outcome == Outcome.PROMOTE_WITH_RETAKES
        assert only.enrollments == ()
        assert only.unplaced_course_ids == (world.c101.pk,)

    def test_rule_changes_are_used(self, world):
        retake = world.graded("F B A+")
        PromotionRule.objects.filter(pk=PromotionRule.current().pk).update(max_failed_courses=0)
        assert decision_of(promotion.preview(world.s1), retake).outcome == Outcome.RETAIN

    def test_queries_do_not_grow_with_students(self, world):
        def count():
            with CaptureQueriesContext(connection) as queries:
                promotion.preview(world.s1)
            return len(queries)

        PromotionRule.current()
        world.graded("A A A")
        world.graded("F A A")
        few = count()
        for letters in ("A F A", "F F F", "B B B", "A+ A+ A+"):
            world.graded(letters)
        assert count() == few


class TestGraduation:
    def last_term_student(self, world, letters):
        offerings = [world.offer(c, world.s1) for c in (world.c201, world.c202)]
        return world.graded(letters, level_term=world.l2, offerings=offerings)

    def test_last_level_term_with_everything_passed_graduates(self, world, admin):
        student = self.last_term_student(world, "A B")
        planned = promotion.preview(world.s1)
        decision = decision_of(planned, student)
        assert decision.outcome == Outcome.GRADUATE
        assert decision.enrollments == ()
        promotion.apply(planned, actor=admin)
        student.refresh_from_db()
        assert student.academic_status == AcademicStatus.GRADUATED
        assert student.level_term == world.l2
        assert new_enrollments(student, world.s2) == set()
        after = promotion.preview(world.s1)
        assert (after.decisions, after.applied_count) == ((), 1)

    def test_last_level_term_with_a_failure_is_retained(self, world):
        student = self.last_term_student(world, "A F")
        decision = decision_of(promotion.preview(world.s1), student)
        assert decision.outcome == Outcome.RETAIN
        assert decision.academic_status == AcademicStatus.ACTIVE
        assert decision.enrollments == (
            promotion.PlannedEnrollment(world.next["C201"].pk, EnrollmentStatus.REGULAR),
            promotion.PlannedEnrollment(world.next["C202"].pk, EnrollmentStatus.RETAKE),
        )

    def test_an_earlier_failure_blocks_graduation_and_is_retaken(self, world):
        student = self.last_term_student(world, "A A")
        old = make_semester("S0", start_date=date(2025, 7, 1), end_date=date(2025, 12, 31))
        add_result(student, world.offer(world.c101, old), "F")
        decision = decision_of(promotion.preview(world.s1), student)
        assert decision.failed_course_ids == (world.c101.pk,)
        assert decision.outcome == Outcome.RETAIN
        assert (world.next["C101"].pk, EnrollmentStatus.RETAKE) in {
            (e.offering_id, e.status) for e in decision.enrollments
        }


class TestApply:
    def test_applied_result_equals_the_preview_exactly(self, world, admin):
        students = [world.graded(x) for x in ("A+ A B", "F B A+", "F F F", "A D C")]
        promotion.set_override(students[3], world.s1, Outcome.RETAIN, "Medical leave", actor=admin)
        before = Enrollment.objects.count()
        planned = promotion.preview(world.s1)
        assert promotion.apply(planned, actor=admin) == 4

        for decision in planned.decisions:
            student = next(s for s in students if s.pk == decision.student_profile_id)
            student.refresh_from_db()
            assert student.level_term_id == decision.to_level_term_id
            assert student.academic_status == decision.academic_status
            assert new_enrollments(student, world.s2) == {
                (e.offering_id, e.status) for e in decision.enrollments
            }
            stored = PromotionDecision.objects.get(student_profile=student, semester=world.s1)
            assert (
                stored.outcome,
                stored.computed_outcome,
                stored.override_reason,
                stored.from_level_term_id,
                stored.to_level_term_id,
                stored.term_gpa,
                stored.cgpa,
                stored.credits_earned,
                stored.failed_courses,
                stored.applied_by,
            ) == (
                decision.outcome,
                decision.computed,
                decision.override_reason,
                decision.from_level_term_id,
                decision.to_level_term_id,
                decision.term_gpa,
                decision.cgpa,
                decision.credits_earned,
                len(decision.failed_course_ids),
                admin,
            )
        assert Enrollment.objects.count() - before == sum(
            len(d.enrollments) for d in planned.decisions
        )

    def test_second_apply_changes_nothing(self, world, admin):
        students = [world.graded(x) for x in ("A+ A B", "F B A+", "F F F")]
        planned = promotion.preview(world.s1)
        promotion.apply(planned, actor=admin)
        snapshot = (
            list(Enrollment.objects.order_by("pk").values_list()),
            [tuple(type(s).objects.filter(pk=s.pk).values_list()) for s in students],
            list(PromotionDecision.objects.order_by("pk").values_list()),
        )
        events = AuditEvent.objects.count()

        assert promotion.apply(planned, actor=admin) == 0
        fresh = promotion.preview(world.s1)
        assert fresh.decisions == ()
        assert fresh.applied_count == 3
        assert promotion.apply(fresh, actor=admin) == 0

        assert snapshot == (
            list(Enrollment.objects.order_by("pk").values_list()),
            [tuple(type(s).objects.filter(pk=s.pk).values_list()) for s in students],
            list(PromotionDecision.objects.order_by("pk").values_list()),
        )
        assert AuditEvent.objects.count() == events

    def test_retake_enrollments_are_created(self, world, admin):
        student = world.graded("F B A+")
        promotion.apply(promotion.preview(world.s1), actor=admin)
        retake = Enrollment.objects.get(student_profile=student, offering=world.next["C101"])
        assert retake.status == EnrollmentStatus.RETAKE

    def test_a_change_after_the_preview_refuses_and_saves_nothing(self, world, admin):
        student = world.graded("A A A")
        planned = promotion.preview(world.s1)
        Result.objects.filter(
            enrollment__student_profile=student, enrollment__offering=world.o101
        ).update(grade=grade("F"), points=grade("F").points)
        with pytest.raises(StalePreview):
            promotion.apply(planned, actor=admin)
        student.refresh_from_db()
        assert student.level_term == world.l1
        assert not PromotionDecision.objects.exists()
        assert new_enrollments(student, world.s2) == set()

    def test_an_override_after_the_preview_refuses(self, world, admin):
        student = world.graded("A A A")
        planned = promotion.preview(world.s1)
        promotion.set_override(student, world.s1, Outcome.RETAIN, "Asked to repeat", actor=admin)
        with pytest.raises(StalePreview):
            promotion.apply(planned, actor=admin)

    def test_audit_has_counts_only(self, world, admin):
        student = world.graded("A A A")
        world.graded("F F F")
        promotion.apply(promotion.preview(world.s1), actor=admin)
        event = AuditEvent.objects.get(action="promotion.applied")
        assert event.object_id == str(world.s1.pk)
        assert event.metadata == {
            "students": 2,
            "promote": 1,
            "promote_with_retakes": 0,
            "retain": 1,
            "graduate": 0,
            "overridden": 0,
            "enrollments_created": 3,
            "unplaced_retakes": 2,
        }
        assert student.registry.external_id not in str(event.metadata)


class TestNextSemesterCourses:
    def test_promoted_students_see_next_terms_courses_once_it_is_current(self, world, admin):
        student = world.graded("A A A")
        promotion.apply(promotion.preview(world.s1), actor=admin)
        world.s1.is_current = False
        world.s1.save()
        world.s2.is_current = True
        world.s2.save()
        assert set(get_current_courses(student)) == {world.next["C201"], world.next["C202"]}

    def test_offerings_added_later_are_enrolled_by_level_term(self, admin):
        world = World(next_offerings=False)
        student = world.graded("A A A")
        promotion.apply(promotion.preview(world.s1), actor=admin)
        world.s1.is_current = False
        world.s1.save()
        world.s2.is_current = True
        world.s2.save()
        later = [world.offer(c, world.s2) for c in (world.c201, world.c202)]
        enrollments.enroll_group(world.program, world.l2, actor=admin)
        assert set(get_current_courses(student)) == set(later)


class TestOverride:
    def test_override_replaces_the_computed_outcome(self, world, admin):
        student = world.graded("A A A")
        promotion.set_override(student, world.s1, Outcome.RETAIN, "Asked to repeat", actor=admin)
        decision = decision_of(promotion.preview(world.s1), student)
        assert (decision.computed, decision.outcome) == (Outcome.PROMOTE, Outcome.RETAIN)
        assert decision.overridden
        assert decision.to_level_term_id == world.l1.pk

    def test_promote_override_with_failures_brings_retakes(self, world, admin):
        student = world.graded("F F F")
        promotion.set_override(student, world.s1, Outcome.PROMOTE, "Board decision", actor=admin)
        decision = decision_of(promotion.preview(world.s1), student)
        assert decision.outcome == Outcome.PROMOTE_WITH_RETAKES
        assert decision.to_level_term_id == world.l2.pk
        assert (world.next["C101"].pk, EnrollmentStatus.RETAKE) in {
            (e.offering_id, e.status) for e in decision.enrollments
        }

    def test_reason_is_mandatory(self, world, admin):
        student = world.graded("A A A")
        with pytest.raises(ValidationError):
            promotion.set_override(student, world.s1, Outcome.RETAIN, "   ", actor=admin)
        assert not PromotionOverride.objects.exists()

    def test_cannot_promote_beyond_the_last_level_term(self, world, admin):
        offering = world.offer(world.c201, world.s1)
        student = world.graded("A", level_term=world.l2, offerings=[offering])
        with pytest.raises(ValidationError):
            promotion.set_override(student, world.s1, Outcome.PROMOTE, "Why not", actor=admin)

    def test_only_students_of_the_semester(self, world, admin):
        outsider = world.student()
        with pytest.raises(ValidationError):
            promotion.set_override(outsider, world.s1, Outcome.RETAIN, "Reason", actor=admin)

    def test_cannot_change_after_apply(self, world, admin):
        student = world.graded("A A A")
        override = promotion.set_override(student, world.s1, Outcome.RETAIN, "Reason", actor=admin)
        promotion.apply(promotion.preview(world.s1), actor=admin)
        with pytest.raises(ValidationError):
            promotion.set_override(student, world.s1, Outcome.PROMOTE, "Reason", actor=admin)
        with pytest.raises(ValidationError):
            promotion.clear_override(override, actor=admin)
        assert PromotionDecision.objects.get().override_reason == "Reason"

    def test_set_and_clear_are_audited_without_the_reason(self, world, admin):
        student = world.graded("A A A")
        override = promotion.set_override(student, world.s1, Outcome.RETAIN, "Private", actor=admin)
        promotion.clear_override(override, actor=admin)
        assert not PromotionOverride.objects.exists()
        events = AuditEvent.objects.filter(action__startswith="promotion.override")
        assert [e.action for e in events.order_by("pk")] == [
            "promotion.override_set",
            "promotion.override_cleared",
        ]
        assert all("Private" not in str(e.metadata) for e in events)


class TestResults:
    def test_save_change_and_publish(self, world, admin):
        students = [world.student() for _ in range(2)]
        rows = [Enrollment.objects.create(student_profile=s, offering=world.o101) for s in students]
        summary = results.save_grades(
            world.o101, {rows[0].pk: grade("A"), rows[1].pk: None}, publish=False, actor=admin
        )
        assert summary == results.SaveSummary(1, 0, 0)
        assert Result.objects.get().points == Decimal("3.75")

        with pytest.raises(ValidationError):
            results.save_grades(world.o101, {rows[1].pk: None}, publish=True, actor=admin)
        assert not Result.objects.filter(published=True).exists()

        summary = results.save_grades(
            world.o101, {rows[0].pk: grade("B"), rows[1].pk: grade("F")}, publish=True, actor=admin
        )
        assert summary == results.SaveSummary(1, 1, 2)
        assert set(Result.objects.values_list("points", "published")) == {
            (Decimal("3.00"), True),
            (Decimal("0.00"), True),
        }
        event = AuditEvent.objects.filter(action="results.saved").latest("pk")
        assert event.metadata == {"created": 1, "changed": 1, "published": 2}

    def test_a_grade_for_another_offering_is_refused(self, world, admin):
        other = Enrollment.objects.create(student_profile=world.student(), offering=world.o102)
        with pytest.raises(ValidationError):
            results.save_grades(world.o101, {other.pk: grade("A")}, publish=False, actor=admin)

    def test_points_are_kept_when_the_scale_changes(self, world):
        student = world.graded("A A A")
        GradeScale.objects.filter(letter="A").update(points=Decimal("3.80"))
        assert set(
            Result.objects.filter(enrollment__student_profile=student).values_list(
                "points", flat=True
            )
        ) == {Decimal("3.75")}

    def test_an_enrollment_with_a_result_cannot_be_removed(self, world, admin):
        student = world.graded("A A A")
        enrollment = Enrollment.objects.filter(student_profile=student).first()
        with pytest.raises(ValidationError):
            enrollments.remove(enrollment, actor=admin)
        assert Enrollment.objects.filter(pk=enrollment.pk).exists()


RESULT_HEADER = "student_id,department,course_code,semester,grade,section,published"


class TestResultImport:
    def run(self, admin, *rows, apply=True):
        text = "\n".join([RESULT_HEADER, *rows]) + "\n"
        return importers.run(
            importers.ResultImporter(), text, apply=apply, actor=admin, request=None
        )

    def enrolled(self, world, external_id):
        student = make_student(world.department, external_id=external_id)
        Enrollment.objects.create(student_profile=student, offering=world.o101)
        return student

    def test_creates_results(self, world, admin):
        first, second = self.enrolled(world, "2101001"), self.enrolled(world, "2101002")
        result = self.run(admin, "2101001,CSE,C101,S1,a+,,yes", "2101002,CSE,C101,S1,F,,")
        assert result.ok and result.created == 2
        assert Result.objects.get(enrollment__student_profile=first).published
        stored = Result.objects.get(enrollment__student_profile=second)
        assert (stored.grade.letter, stored.points, stored.published) == ("F", Decimal("0"), False)

    def test_row_errors(self, world, admin):
        self.enrolled(world, "2101001")
        make_student(world.department, external_id="2101009")
        self.enrolled(world, "2101002")
        result = self.run(
            admin,
            "2101001,CSE,C101,S1,Z,,",
            "2101009,CSE,C101,S1,A,,",
            "2101002,CSE,C101,S1,A,,maybe",
        )
        assert [(e.line, e.column) for e in result.errors] == [
            (2, "grade"),
            (3, "student_id"),
            (4, "published"),
        ]
        assert not Result.objects.exists()

    def test_existing_results_are_not_overwritten(self, world, admin):
        student = self.enrolled(world, "2101001")
        Result.objects.create(
            enrollment=student.enrollments.get(), grade=grade("B"), points=grade("B").points
        )
        result = self.run(admin, "2101001,CSE,C101,S1,A,,")
        assert [(e.line, e.column) for e in result.errors] == [(2, "student_id")]
        assert Result.objects.get().grade.letter == "B"

    def test_template_header(self):
        header = importers.template_rows(importers.ResultImporter)[0]
        assert header == tuple(RESULT_HEADER.split(","))
        assert importers.IMPORTERS["results"] is importers.ResultImporter


GET_ONLY = {"/manage/results/", "/manage/promotion/"}


class TestScreens:
    def urls(self, world, student):
        return [
            reverse("academics:results"),
            reverse("academics:grade_sheet", args=[world.o101.pk]),
            reverse("academics:promotion"),
            reverse("academics:promotion_rule"),
            reverse("academics:promotion_confirm", args=[world.s1.pk]),
            reverse("academics:promotion_override", args=[world.s1.pk, student.pk]),
        ]

    def test_only_admins(self, client, world):
        student = world.graded("A A A")
        others = [make_hod(world.department), claim(make_teacher()), claim(make_student())]
        for user in others:
            sign_in(client, user)
            for url in self.urls(world, student):
                assert client.get(url).status_code == 403, url
                if url not in GET_ONLY:
                    assert client.post(url).status_code == 403, url
        client.logout()
        for url in self.urls(world, student):
            assert client.get(url).status_code == 302, url

    def test_results_index_and_grade_sheet(self, admin_client, world):
        student = make_student(world.department, external_id="2109999")
        enrollment = Enrollment.objects.create(student_profile=student, offering=world.o101)
        body = admin_client.get(reverse("academics:results")).content.decode()
        assert "C101" in body and "Not published" in body

        url = reverse("academics:grade_sheet", args=[world.o101.pk])
        assert "2109999" in admin_client.get(url).content.decode()
        response = admin_client.post(
            url, {f"grade_{enrollment.pk}": grade("A-").pk, "publish": "1"}
        )
        assert response.status_code == 302
        stored = Result.objects.get()
        assert (stored.grade.letter, stored.published) == ("A-", True)

    def test_publishing_with_a_missing_grade_shows_an_error(self, admin_client, world):
        enrollment = Enrollment.objects.create(student_profile=world.student(), offering=world.o101)
        url = reverse("academics:grade_sheet", args=[world.o101.pk])
        response = admin_client.post(url, {f"grade_{enrollment.pk}": "", "publish": "1"})
        assert response.status_code == 200
        assert "needs a grade" in response.content.decode()

    def test_rule_screen_saves_and_audits(self, admin_client):
        url = reverse("academics:promotion_rule")
        assert admin_client.get(url).status_code == 200
        data = {
            "max_failed_courses": 1,
            "min_cgpa": "2.25",
            "min_credits": "9",
            "retake_policy": RetakePolicy.BEST,
        }
        assert admin_client.post(url, data).status_code == 302
        rule = PromotionRule.current()
        assert (rule.max_failed_courses, rule.min_cgpa, rule.retake_policy) == (
            1,
            Decimal("2.25"),
            RetakePolicy.BEST,
        )
        event = AuditEvent.objects.get(action="promotion.rule_changed")
        assert event.metadata == {
            "changed": ["max_failed_courses", "min_cgpa", "min_credits", "retake_policy"]
        }

    def test_preview_confirm_apply(self, admin_client, world):
        student = world.graded("F B A+")
        preview_url = reverse("academics:promotion")
        body = admin_client.get(preview_url, {"semester": world.s1.pk}).content.decode()
        assert student.registry.external_id in body
        assert "Promote with retakes" in body

        fingerprint = promotion.preview(world.s1).fingerprint()
        confirm = reverse("academics:promotion_confirm", args=[world.s1.pk])
        assert admin_client.get(confirm, {"fingerprint": "stale"}).status_code == 302
        assert admin_client.get(confirm, {"fingerprint": fingerprint}).status_code == 200
        response = admin_client.post(confirm, {"fingerprint": fingerprint})
        assert response.status_code == 302
        student.refresh_from_db()
        assert student.level_term == world.l2

        # The same confirmation again finds a changed preview and applies nothing.
        admin_client.post(confirm, {"fingerprint": fingerprint})
        assert PromotionDecision.objects.count() == 1

    def test_override_screen(self, admin_client, world):
        student = world.graded("A A A")
        url = reverse("academics:promotion_override", args=[world.s1.pk, student.pk])
        assert admin_client.get(url).status_code == 200
        response = admin_client.post(url, {"outcome": Outcome.RETAIN, "reason": ""})
        assert response.status_code == 200
        assert not PromotionOverride.objects.exists()

        admin_client.post(url, {"outcome": Outcome.RETAIN, "reason": "Asked to repeat"})
        assert PromotionOverride.objects.get().outcome == Outcome.RETAIN
        body = admin_client.get(reverse("academics:promotion")).content.decode()
        assert "Overridden" in body

        admin_client.post(url, {"action": "clear"})
        assert not PromotionOverride.objects.exists()

    def test_override_for_a_student_outside_the_semester_is_404(self, admin_client, world):
        url = reverse("academics:promotion_override", args=[world.s1.pk, world.student().pk])
        assert admin_client.get(url).status_code == 404
