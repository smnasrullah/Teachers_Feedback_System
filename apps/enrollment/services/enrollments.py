"""Enroll students (a whole level/term at once, or one at a time) and remove enrollments.

Every change is audited with counts only: never a student ID or a name.
"""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from apps.academics.models import CourseOffering, Result, Semester
from apps.accounts.models import AcademicStatus, StudentProfile
from apps.auditlog.services import audit
from apps.enrollment.models import Enrollment, EnrollmentStatus

BULK_BATCH = 1000


@dataclass(frozen=True)
class GroupPlan:
    """What enrolling a group would do: students x matching offerings, minus what exists."""

    students: int
    offerings: int
    new: list[Enrollment]


def current_semester() -> Semester:
    semester = Semester.objects.filter(is_current=True).first()
    if semester is None:
        raise ValidationError(_("There is no current semester."), code="no_current_semester")
    return semester


def plan_group(program, level_term) -> GroupPlan:
    """Active students of ``program`` at ``level_term`` x the current semester's compulsory
    offerings of that program and level/term.

    A student joins an offering when it has no section, or when it has the student's section.
    Electives are enrolled one student at a time.
    """
    semester = current_semester()
    students = list(
        StudentProfile.objects.filter(
            program=program, level_term=level_term, academic_status=AcademicStatus.ACTIVE
        ).values_list("pk", "section")
    )
    offerings = list(
        CourseOffering.objects.filter(
            semester=semester,
            course__program=program,
            course__level_term=level_term,
            course__is_elective=False,
        ).values_list("pk", "section")
    )
    stored = set(
        Enrollment.objects.filter(offering_id__in=[pk for pk, _section in offerings]).values_list(
            "student_profile_id", "offering_id"
        )
    )
    new = [
        Enrollment(student_profile_id=student, offering_id=offering)
        for student, student_section in students
        for offering, offering_section in offerings
        if offering_section in ("", student_section) and (student, offering) not in stored
    ]
    return GroupPlan(len(students), len(offerings), new)


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
    if Result.objects.filter(enrollment=enrollment).exists():
        raise ValidationError(
            _("This enrollment has a result, so it cannot be removed."), code="has_result"
        )
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
