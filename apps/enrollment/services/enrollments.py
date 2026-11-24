"""Enroll students (by the level/term rule, or one at a time) and remove enrollments.

Every change is audited with counts only: never a student ID or a name.
"""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from apps.academics.models import CourseOffering, Result, Semester
from apps.academics.services import semesters
from apps.accounts.models import AcademicStatus, StudentProfile
from apps.auditlog.services import audit
from apps.enrollment.models import Enrollment, EnrollmentStatus
from apps.feedback.models import Draft, SubmissionReceipt

BULK_BATCH = 1000


@dataclass(frozen=True)
class GroupPlan:
    """What enrolling a group would do: students x matching offerings, minus what exists."""

    students: int
    offerings: int
    new: list[Enrollment]


def require_current_semester() -> Semester:
    semester = semesters.current_semester()
    if semester is None:
        raise ValidationError(_("There is no current semester."), code="no_current_semester")
    return semester


def plan_rule(students, offerings) -> GroupPlan:
    """The level/term rule: an active student joins every compulsory offering of their program
    and level/term, when the offering has no section or has the student's section.

    ``students`` and ``offerings`` are querysets to match against each other; pairs that are
    already enrolled are left out. Electives and retakes are enrolled one student at a time.
    """
    students = list(
        students.filter(academic_status=AcademicStatus.ACTIVE).values_list(
            "pk", "program_id", "level_term_id", "section"
        )
    )
    offerings = list(
        offerings.filter(course__is_elective=False).values_list(
            "pk", "course__program_id", "course__level_term_id", "section"
        )
    )
    by_place: dict[tuple[int, int], list[tuple[int, str]]] = {}
    for pk, program, level_term, section in offerings:
        by_place.setdefault((program, level_term), []).append((pk, section))
    pairs = [
        (student, offering)
        for student, program, level_term, student_section in students
        for offering, offering_section in by_place.get((program, level_term), [])
        if offering_section in ("", student_section)
    ]
    stored = set(
        Enrollment.objects.filter(
            student_profile_id__in={student for student, _offering in pairs},
            offering_id__in={offering for _student, offering in pairs},
        ).values_list("student_profile_id", "offering_id")
    )
    new = [
        Enrollment(student_profile_id=student, offering_id=offering)
        for student, offering in pairs
        if (student, offering) not in stored
    ]
    return GroupPlan(len(students), len(offerings), new)


def plan_group(program, level_term) -> GroupPlan:
    """Active students of ``program`` at ``level_term`` x the current semester's compulsory
    offerings of that program and level/term (see ``plan_rule``)."""
    semester = require_current_semester()
    return plan_rule(
        StudentProfile.objects.filter(program=program, level_term=level_term),
        CourseOffering.objects.filter(
            semester=semester, course__program=program, course__level_term=level_term
        ),
    )


@transaction.atomic
def apply_rule(*, students=None, offerings=None, trigger: str, actor=None, request=None) -> int:
    """Enroll by the level/term rule in the current semester, the moment a student is
    registered or moved, or an offering is created: the same rule the Admin's group enrolment
    applies, so nobody waits for the Admin to run it again. Returns how many were created.

    Only today's semester counts: the next semester's places come from promotion.
    """
    semester = semesters.current_semester()
    if semester is None:
        return 0
    current = CourseOffering.objects.filter(semester=semester)
    plan = plan_rule(
        StudentProfile.objects.all() if students is None else students,
        current if offerings is None else current.filter(pk__in=offerings),
    )
    if not plan.new:
        return 0
    Enrollment.objects.bulk_create(plan.new, batch_size=BULK_BATCH, ignore_conflicts=True)
    audit.record(
        "enrollment.rule_applied",
        request=request,
        actor=actor,
        metadata={"trigger": trigger, "semester_id": semester.pk, "created": len(plan.new)},
    )
    return len(plan.new)


@transaction.atomic
def enroll_group(program, level_term, *, actor, request=None) -> GroupPlan:
    plan = plan_group(program, level_term)
    Enrollment.objects.bulk_create(plan.new, batch_size=BULK_BATCH, ignore_conflicts=True)
    audit.record(
        "enrollment.group_enrolled",
        request=request,
        actor=actor,
        department_id=program.department_id,
        metadata={
            "program_id": program.pk,
            "level_term_id": level_term.pk,
            "students": plan.students,
            "offerings": plan.offerings,
            "created": len(plan.new),
        },
    )
    return plan


@transaction.atomic
def enroll(student_profile, offering, *, status=EnrollmentStatus.REGULAR, actor, request=None):
    """Add one course to one student: an offering of the semester running today."""
    current = semesters.current_semester()
    if current is None or offering.semester_id != current.pk:
        raise ValidationError(
            _(
                "This course is not offered in the current semester. Choose an offering of "
                "%(semester)s."
            )
            if current
            else _("There is no current semester."),
            code="wrong_semester",
            params={"semester": current.name if current else ""},
        )
    try:
        with transaction.atomic():
            enrollment = Enrollment.objects.create(
                student_profile=student_profile, offering=offering, status=status
            )
    except IntegrityError:
        raise ValidationError(
            _("This student is already enrolled in this offering."), code="duplicate"
        ) from None
    audit.record(
        "enrollment.created",
        request=request,
        actor=actor,
        target=enrollment,
        department_id=offering.course.department_id,
        metadata={"status": status},
    )
    return enrollment


@transaction.atomic
def remove(enrollment, *, actor, request=None) -> None:
    """Drop a course the student has not given feedback for yet. Anonymous answers are never
    touched; the student's own unfinished draft for the course goes with the enrollment."""
    if Result.objects.filter(enrollment=enrollment).exists():
        raise ValidationError(
            _("This enrollment has a result, so it cannot be removed."), code="has_result"
        )
    pair = {
        "student_profile_id": enrollment.student_profile_id,
        "offering_id": enrollment.offering_id,
    }
    if SubmissionReceipt.objects.filter(**pair).exists():
        raise ValidationError(
            _(
                "The student has already given feedback for this course, so it cannot be "
                "removed. The response rate would no longer add up."
            ),
            code="has_feedback",
        )
    Draft.objects.filter(**pair).delete()
    department_id = enrollment.offering.course.department_id
    audit.record(
        "enrollment.removed",
        request=request,
        actor=actor,
        target=enrollment,
        department_id=department_id,
        metadata={"status": enrollment.status},
    )
    enrollment.delete()
