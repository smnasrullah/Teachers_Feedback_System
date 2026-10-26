"""Read-side queries over the academic structure."""

from apps.academics.models import CourseOffering


def get_current_courses(student_profile) -> list[CourseOffering]:
    """Offerings of the current semester that ``student_profile`` takes.

    Enrollment arrives with P07. Until then a student takes what the curriculum places at
    their level/term in their department; P07 replaces this join with the student's
    ``Enrollment`` rows and keeps the signature.
    """
    return list(
        CourseOffering.objects.filter(
            semester__is_current=True,
            course__level_term_id=student_profile.level_term_id,
            course__department_id=student_profile.program.department_id,
        ).select_related("course", "semester", "teacher__registry")
    )
