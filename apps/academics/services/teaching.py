"""The one answer to "which courses does this teacher teach in a semester?".

The teacher's dashboard, the course overview of a round and the ``explain_visibility``
command all read it. A head of department is a teacher too: their own courses come from
here, the department's from ``apps.reports.services.department``.
"""

from apps.academics.models import CourseOffering


def offerings_for_teacher(teacher_profile, semester) -> list[CourseOffering]:
    """The offerings of ``semester`` assigned to ``teacher_profile``, by course code."""
    if semester is None or teacher_profile is None:
        return []
    return list(
        CourseOffering.objects.filter(teacher=teacher_profile, semester=semester)
        .select_related("course__department", "semester")
        .order_by("course__code", "section", "pk")
    )
