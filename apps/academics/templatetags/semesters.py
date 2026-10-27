"""``{% semester_badge %}``: today's semester and its last day, for every dashboard."""

from django import template

from apps.academics.services import semesters

register = template.Library()


@register.inclusion_tag("components/semester_badge.html")
def semester_badge():
    semester = semesters.current_semester()
    return {
        "semester": semester,
        "ends_on": semesters.short_date(semester.end_date) if semester else "",
    }
