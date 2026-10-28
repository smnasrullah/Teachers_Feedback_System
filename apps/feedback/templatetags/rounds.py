"""``{% window_countdown %}``: the live countdown of a feedback round."""

from django import template
from django.utils import timezone
from django.utils.translation import gettext

from apps.core.templatetags.ui import countdown
from apps.feedback.models import WindowStatus

register = template.Library()


@register.simple_tag
def window_countdown(window):
    """ "Closes in" for an open round, "Opens in" for an upcoming one, nothing otherwise."""
    if window is None or not window.is_active:
        return ""
    status = window.status(timezone.now())
    if status == WindowStatus.OPEN:
        return countdown(window.closes_at, gettext("Closes in"), gettext("Closed"))
    if status == WindowStatus.UPCOMING:
        return countdown(window.opens_at, gettext("Opens in"), gettext("Open now"))
    return ""
