"""``{% semester_badge %}``, ``{% semester_countdown %}``: today's semester on every dashboard."""

from django import template
from django.utils.translation import gettext

from apps.academics.services import semesters
from apps.core.templatetags.ui import countdown

register = template.Library()


@register.inclusion_tag("components/semester_badge.html")
def semester_badge():
    semester = semesters.current_semester()
    return {
        "semester": semester,
        "ends_on": semesters.short_date(semester.end_date) if semester else "",
    }


@register.simple_tag
def semester_countdown():
    """A live "Semester ends in" countdown for today's semester, or nothing between semesters."""
    semester = semesters.current_semester()
    if semester is None:
        return ""
    return countdown(
        semesters.ends_at(semester), gettext("Semester ends in"), gettext("Semester ended")
    )
