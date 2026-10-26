"""Read-side queries over the academic structure."""

from apps.academics.models import CourseOffering


def get_current_courses(student_profile) -> list[CourseOffering]:
    """Offerings of the current semester that ``student_profile`` is enrolled in."""
    return list(
        CourseOffering.objects.filter(
            semester__is_current=True, enrollments__student_profile=student_profile
        ).select_related("course", "semester", "teacher__registry")
    )
