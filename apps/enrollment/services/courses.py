"""The one answer to "which courses does this student take this semester?".

The student's dashboard, the feedback form's access check, the done page and the
``explain_visibility`` command all read it, so they can never disagree.
"""

from apps.academics.models import CourseOffering
from apps.enrollment.models import Enrollment, EnrollmentStatus


def courses_for_student(
    student_profile, semester, *, include_retakes: bool = True
) -> list[CourseOffering]:
    """The offerings of ``semester`` that ``student_profile`` is enrolled in (regular, and
    retakes unless ``include_retakes`` is false), by course code. ``None`` semester: none."""
    if semester is None:
        return []
    enrollments = Enrollment.objects.filter(
        student_profile=student_profile, offering__semester=semester
    )
    if not include_retakes:
        enrollments = enrollments.filter(status=EnrollmentStatus.REGULAR)
    return list(
        CourseOffering.objects.filter(pk__in=enrollments.values("offering_id"))
        .select_related("course__department", "semester", "teacher__registry")
        .order_by("course__code", "section", "pk")
    )
