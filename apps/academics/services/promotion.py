"""Semester-end promotion (BLUEPRINT §3 F2, promotion rule under §5.4).

``preview(semester)`` only reads: for every active student enrolled in ``semester`` whose
results there are all published, it applies the rule (or the admin's override) and plans the
effects. ``apply(preview)`` locks those students, recomputes the preview and refuses when any
decision differs from what the admin saw, so what is applied always equals what was previewed.
A student is applied once per semester (``PromotionDecision``): applying again changes nothing.

Effects of an outcome:
- promote / promote with retakes: next level/term of the student's program;
- retain: same level/term;
- graduate: status "graduated" (only computed on the program's last level/term).
Unless graduating, the student is enrolled in the next semester's compulsory offerings of the
level/term they move to, and failed courses become retake enrollments where offered.
"""

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from apps.academics.models import (
    Course,
    CourseOffering,
    LevelTerm,
    Outcome,
    PromotionDecision,
    PromotionOverride,
    PromotionRule,
    Semester,
    SemesterStatus,
)
from apps.academics.services import gpa, semesters
from apps.accounts.models import AcademicStatus, StudentProfile
from apps.auditlog.services import audit
from apps.enrollment.models import Enrollment, EnrollmentStatus

BULK_BATCH = 1000
PROMOTING = frozenset({Outcome.PROMOTE, Outcome.PROMOTE_WITH_RETAKES})


class StalePreview(ValidationError):
    """Results, overrides, the rule or enrollments changed after the preview was made."""


@dataclass(frozen=True)
class PlannedEnrollment:
    offering_id: int
    status: str


@dataclass(frozen=True)
class Decision:
    student_profile_id: int
    from_level_term_id: int
    to_level_term_id: int
    academic_status: str
    term_gpa: Decimal
    cgpa: Decimal
    credits_earned: Decimal
    failed_course_ids: tuple[int, ...]
    computed: str
    outcome: str
    override_reason: str
    enrollments: tuple[PlannedEnrollment, ...]
    unplaced_course_ids: tuple[int, ...]

    @property
    def overridden(self) -> bool:
        return bool(self.override_reason)


@dataclass(frozen=True)
class RuleSnapshot:
    max_failed_courses: int
    min_cgpa: Decimal
    min_credits: Decimal
    retake_policy: str


@dataclass(frozen=True)
class Preview:
    semester_id: int
    target_semester_id: int | None
    rule: RuleSnapshot
    decisions: tuple[Decision, ...]
    pending_ids: tuple[int, ...]
    applied_count: int

    def fingerprint(self) -> str:
        """A digest of everything shown, so a confirmation can prove it saw this preview."""
        canonical = json.dumps(asdict(self), default=str, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def counts(self) -> Counter:
        return Counter(decision.outcome for decision in self.decisions)


def decide(rule: RuleSnapshot, *, failed: int, cgpa: Decimal, credits: Decimal, last: bool) -> str:
    """The rule itself: every limit must hold; then the last level/term graduates when nothing
    is left to retake, and any other level/term moves on (with retakes when something failed)."""
    meets = (
        failed <= rule.max_failed_courses and cgpa >= rule.min_cgpa and credits >= rule.min_credits
    )
    if not meets:
        return Outcome.RETAIN
    if last:
        return Outcome.RETAIN if failed else Outcome.GRADUATE
    return Outcome.PROMOTE_WITH_RETAKES if failed else Outcome.PROMOTE


def has_ended(semester: Semester) -> bool:
    """Promotion waits for the semester's last day to pass; moving the end date moves it too."""
    return semester.status(semesters.today()) == SemesterStatus.ENDED


def next_semester(semester: Semester) -> Semester | None:
    return (
        Semester.objects.filter(start_date__gt=semester.start_date).order_by("start_date").first()
    )


def _ladders(program_ids) -> dict[int, list[tuple[int, int]]]:
    """Per program: (order, level/term id) of the levels/terms its curriculum has courses in."""
    ladders: dict[int, set[tuple[int, int]]] = {}
    rows = Course.objects.filter(program_id__in=program_ids).values_list(
        "program_id", "level_term__order", "level_term_id"
    )
    for program, order, level_term in rows:
        ladders.setdefault(program, set()).add((order, level_term))
    return {program: sorted(steps) for program, steps in ladders.items()}


def _next_level_term(ladder: list[tuple[int, int]], order: int) -> int | None:
    return next((level_term for step, level_term in ladder if step > order), None)


def next_level_term(student_profile) -> LevelTerm | None:
    """The level/term after the student's current one in their program, ``None`` on the last."""
    ladder = _ladders([student_profile.program_id]).get(student_profile.program_id, [])
    following = _next_level_term(ladder, student_profile.level_term.order)
    return LevelTerm.objects.get(pk=following) if following else None


class _Placement:
    """Offerings of the target semester and who is already enrolled in them."""

    def __init__(self, target: Semester | None, student_ids):
        self.target = target
        self.by_course: dict[int, list[tuple[str, int]]] = {}
        self.compulsory: dict[tuple[int, int], list[tuple[int, int, str]]] = {}
        self.enrolled_courses: set[tuple[int, int]] = set()
        if target is None:
            return
        offerings = (
            CourseOffering.objects.filter(semester=target)
            .order_by("pk")
            .values_list(
                "pk",
                "course_id",
                "section",
                "course__program_id",
                "course__level_term_id",
                "course__is_elective",
            )
        )
        for pk, course, section, program, level_term, elective in offerings:
            self.by_course.setdefault(course, []).append((section, pk))
            if not elective:
                self.compulsory.setdefault((program, level_term), []).append((pk, course, section))
        self.enrolled_courses = set(
            Enrollment.objects.filter(
                offering__semester=target, student_profile_id__in=list(student_ids)
            ).values_list("student_profile_id", "offering__course_id")
        )

    def retake_offering(self, course: int, section: str) -> int | None:
        """Prefer the student's section, then an offering without sections, then any."""
        choices = sorted(self.by_course.get(course, []))
        for wanted in (section, ""):
            for offering_section, pk in choices:
                if offering_section == wanted:
                    return pk
        return choices[0][1] if choices else None

    def plan(self, student, level_term: int, failed: tuple[int, ...]):
        """Enrollments to create and failed courses with no offering to retake them in."""
        if self.target is None:
            return (), failed
        planned, unplaced = [], []
        for course in failed:
            if (student.pk, course) in self.enrolled_courses:
                continue
            offering = self.retake_offering(course, student.section)
            if offering is None:
                unplaced.append(course)
            else:
                planned.append(PlannedEnrollment(offering, EnrollmentStatus.RETAKE))
        for offering, course, section in self.compulsory.get((student.program_id, level_term), []):
            if course in failed or (student.pk, course) in self.enrolled_courses:
                continue
            if section in ("", student.section):
                planned.append(PlannedEnrollment(offering, EnrollmentStatus.REGULAR))
        return tuple(sorted(planned, key=lambda item: item.offering_id)), tuple(unplaced)


def _snapshot(rule: PromotionRule) -> RuleSnapshot:
    return RuleSnapshot(
        rule.max_failed_courses, rule.min_cgpa, rule.min_credits, rule.retake_policy
    )


def _effective(override: PromotionOverride | None, computed: str, *, failed, last) -> tuple:
    """The outcome after the override, and its reason. "Promote" is labelled by whether
    retakes follow; an override that can no longer apply (no next level/term) is ignored."""
    if override is None or (override.outcome in PROMOTING and last):
        return computed, ""
    outcome = override.outcome
    if outcome in PROMOTING:
        outcome = Outcome.PROMOTE_WITH_RETAKES if failed else Outcome.PROMOTE
    return outcome, override.reason


def preview(semester: Semester) -> Preview:
    rule = _snapshot(PromotionRule.current())
    target = next_semester(semester)
    enrolled = Enrollment.objects.filter(
        offering__semester=semester, student_profile__academic_status=AcademicStatus.ACTIVE
    )
    student_ids = set(enrolled.values_list("student_profile_id", flat=True))
    applied = set(
        PromotionDecision.objects.filter(semester=semester).values_list(
            "student_profile_id", flat=True
        )
    )
    pending = (
        set(enrolled.exclude(result__published=True).values_list("student_profile_id", flat=True))
        - applied
    )
    candidates = sorted(student_ids - applied - pending)
    students = StudentProfile.objects.filter(pk__in=candidates).select_related("level_term")
    attempts = gpa.load_attempts(candidates, semester)
    overrides = {
        override.student_profile_id: override
        for override in PromotionOverride.objects.filter(
            semester=semester, student_profile_id__in=candidates
        )
    }
    ladders = _ladders({student.program_id for student in students})
    placement = _Placement(target, candidates)
    decisions = []
    for student in students.order_by("pk"):
        own = attempts.get(student.pk, [])
        failed = gpa.failed_courses(own, rule.retake_policy)
        cgpa = gpa.cgpa(own, rule.retake_policy)
        credits = sum(
            (a.credit for a in own if a.semester_id == semester.pk and a.passed), Decimal(0)
        )
        following = _next_level_term(ladders.get(student.program_id, []), student.level_term.order)
        last = following is None
        computed = decide(rule, failed=len(failed), cgpa=cgpa, credits=credits, last=last)
        outcome, reason = _effective(overrides.get(student.pk), computed, failed=failed, last=last)
        level_term = following if outcome in PROMOTING else student.level_term_id
        if outcome == Outcome.GRADUATE:
            enrollments, unplaced = (), ()
        else:
            enrollments, unplaced = placement.plan(student, level_term, failed)
        decisions.append(
            Decision(
                student_profile_id=student.pk,
                from_level_term_id=student.level_term_id,
                to_level_term_id=level_term,
                academic_status=(
                    AcademicStatus.GRADUATED
                    if outcome == Outcome.GRADUATE
                    else AcademicStatus.ACTIVE
                ),
                term_gpa=gpa.term_gpa(own, semester.pk),
                cgpa=cgpa,
                credits_earned=credits,
                failed_course_ids=failed,
                computed=computed,
                outcome=outcome,
                override_reason=reason,
                enrollments=enrollments,
                unplaced_course_ids=unplaced,
            )
        )
    return Preview(
        semester_id=semester.pk,
        target_semester_id=target.pk if target else None,
        rule=rule,
        decisions=tuple(decisions),
        pending_ids=tuple(sorted(pending)),
        applied_count=len(applied),
    )


@transaction.atomic
def apply(planned: Preview, *, actor, request=None) -> int:
    """Apply ``planned`` exactly; returns how many students changed (0 when already applied).
    Refused until the semester has ended."""
    semester = Semester.objects.get(pk=planned.semester_id)
    if not has_ended(semester):
        raise ValidationError(
            _("Promotion for %(semester)s can be applied after it ends on %(end)s."),
            code="not_ended",
            params={"semester": semester.name, "end": semesters.short_date(semester.end_date)},
        )
    by_student = {decision.student_profile_id: decision for decision in planned.decisions}
    profiles = {
        profile.pk: profile
        for profile in StudentProfile.objects.select_for_update()
        .filter(pk__in=list(by_student))
        .order_by("pk")
    }
    done = set(
        PromotionDecision.objects.filter(
            semester=semester, student_profile_id__in=list(by_student)
        ).values_list("student_profile_id", flat=True)
    )
    todo = [decision for pk, decision in by_student.items() if pk not in done]
    if not todo:
        return 0
    fresh = {decision.student_profile_id: decision for decision in preview(semester).decisions}
    if any(fresh.get(decision.student_profile_id) != decision for decision in todo):
        raise StalePreview(
            _("Results, overrides or enrollments changed after the preview. Review it again."),
            code="stale",
        )
    for decision in todo:
        profile = profiles[decision.student_profile_id]
        profile.level_term_id = decision.to_level_term_id
        profile.academic_status = decision.academic_status
    StudentProfile.objects.bulk_update(
        [profiles[decision.student_profile_id] for decision in todo],
        ["level_term", "academic_status"],
        batch_size=BULK_BATCH,
    )
    PromotionDecision.objects.bulk_create(
        [
            PromotionDecision(
                student_profile_id=decision.student_profile_id,
                semester=semester,
                outcome=decision.outcome,
                computed_outcome=decision.computed,
                override_reason=decision.override_reason,
                from_level_term_id=decision.from_level_term_id,
                to_level_term_id=decision.to_level_term_id,
                term_gpa=decision.term_gpa,
                cgpa=decision.cgpa,
                credits_earned=decision.credits_earned,
                failed_courses=len(decision.failed_course_ids),
                applied_by=actor,
            )
            for decision in todo
        ],
        batch_size=BULK_BATCH,
    )
    enrollments = [
        Enrollment(
            student_profile_id=decision.student_profile_id,
            offering_id=planned_enrollment.offering_id,
            status=planned_enrollment.status,
        )
        for decision in todo
        for planned_enrollment in decision.enrollments
    ]
    try:
        with transaction.atomic():
            Enrollment.objects.bulk_create(enrollments, batch_size=BULK_BATCH)
    except IntegrityError:
        raise StalePreview(
            _("Results, overrides or enrollments changed after the preview. Review it again."),
            code="stale",
        ) from None
    outcomes = Counter(decision.outcome for decision in todo)
    audit.record(
        "promotion.applied",
        request=request,
        actor=actor,
        target=semester,
        metadata={
            "students": len(todo),
            **{outcome: outcomes.get(outcome, 0) for outcome in Outcome.values},
            "overridden": sum(decision.overridden for decision in todo),
            "enrollments_created": len(enrollments),
            "unplaced_retakes": sum(len(decision.unplaced_course_ids) for decision in todo),
        },
    )
    return len(todo)


def _refuse_if_applied(student_profile, semester) -> None:
    if PromotionDecision.objects.filter(
        student_profile=student_profile, semester=semester
    ).exists():
        raise ValidationError(
            _("The promotion of this student for this semester is already applied."),
            code="applied",
        )


@transaction.atomic
def set_override(student_profile, semester, outcome, reason, *, actor, request=None):
    """Record the admin's outcome for one student; the reason is mandatory."""
    reason = reason.strip()
    if not reason:
        raise ValidationError(_("Give a reason for the override."), code="reason")
    _refuse_if_applied(student_profile, semester)
    if not Enrollment.objects.filter(
        student_profile=student_profile,
        offering__semester=semester,
        student_profile__academic_status=AcademicStatus.ACTIVE,
    ).exists():
        raise ValidationError(
            _("Only active students enrolled in this semester can be overridden."),
            code="not_enrolled",
        )
    if outcome in PROMOTING and next_level_term(student_profile) is None:
        raise ValidationError(
            _("This is the last level/term of the student's program: choose graduate or retain."),
            code="last_level_term",
        )
    override, created = PromotionOverride.objects.update_or_create(
        student_profile=student_profile,
        semester=semester,
        defaults={"outcome": outcome, "reason": reason},
    )
    audit.record(
        "promotion.override_set",
        request=request,
        actor=actor,
        target=override,
        department_id=student_profile.registry.department_id,
        metadata={"semester_id": semester.pk, "outcome": outcome, "created": created},
    )
    return override


@transaction.atomic
def clear_override(override, *, actor, request=None) -> None:
    _refuse_if_applied(override.student_profile, override.semester)
    audit.record(
        "promotion.override_cleared",
        request=request,
        actor=actor,
        target=override,
        department_id=override.student_profile.registry.department_id,
        metadata={"semester_id": override.semester_id, "outcome": override.outcome},
    )
    override.delete()


@transaction.atomic
def save_rule(form, *, actor, request=None) -> PromotionRule:
    changed = sorted(form.changed_data)
    rule = form.save()
    if changed:
        audit.record(
            "promotion.rule_changed",
            request=request,
            actor=actor,
            target=rule,
            metadata={"changed": changed},
        )
    return rule
