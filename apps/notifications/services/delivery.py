"""Hand one message to a user on every channel they can be reached on.

The in-app notice is always created. E-mail and text messages go out only when the user has the
contact detail and, unless the caller overrides it, outside quiet hours. Every attempt is
logged as kind, channel and outcome; the text and the destination are never stored or logged.
"""

from django.conf import settings
from django.utils import timezone, translation
from django.utils.dateparse import parse_datetime

from apps.core.services import system_settings
from apps.notifications.models import DeliveryLog, DeliveryStatus, Notification
from apps.notifications.senders import EMAIL, EXTERNAL_CHANNELS, IN_APP, SMS, Message, get_sender
from apps.notifications.services import messages

# What to do with an e-mail or text that falls in quiet hours.
DEFER = "defer"  # leave it unsent and unrecorded so a later run sends it
SKIP = "skip"  # drop it and log that it was skipped
IGNORE = "ignore"  # send anyway (an Admin's explicit test)


def in_quiet_hours(now) -> bool:
    start = system_settings.get("QUIET_HOURS_START")
    end = system_settings.get("QUIET_HOURS_END")
    if start == end:
        return False
    hour = timezone.localtime(now).hour
    return start <= hour < end if start < end else hour >= start or hour < end


def values_from_params(params: dict, url: str = "") -> dict:
    """Placeholder values from a notice's stored parameters, in the active language."""
    closes_at = parse_datetime(params["closes_at"]) if params.get("closes_at") else None
    return {
        "round": params.get("round", ""),
        "course": params.get("course", ""),
        "pending": params.get("pending", ""),
        "closes_at": messages.local_time(closes_at) if closes_at else "",
        "time_left": messages.time_left(params["hours"]) if "hours" in params else "",
        "link": f"{settings.SITE_URL}{url}",
    }


def _destination(user, channel: str) -> str | None:
    if channel == EMAIL:
        return user.contact_email or None
    if channel == SMS and settings.NOTIFICATION_SMS_ENABLED:
        return user.contact_phone or None
    return None


def _log(user, kind: str, channel: str, status: str, detail: str = "") -> None:
    DeliveryLog.objects.create(user=user, kind=kind, channel=channel, status=status, detail=detail)


def _send(user, kind, channel, destination, params, url, language) -> None:
    with translation.override(language):
        text = messages.render(kind, language, values_from_params(params, url))
    try:
        get_sender(channel).send(Message(channel, destination, text.subject, text.body))
    except Exception as error:
        _log(user, kind, channel, DeliveryStatus.FAILED, type(error).__name__)
    else:
        _log(user, kind, channel, DeliveryStatus.SENT)


def notify(
    user,
    kind: str,
    params: dict,
    *,
    url: str,
    now,
    skip=frozenset(),
    quiet: str = DEFER,
    language: str | None = None,
) -> set[str]:
    """Send ``kind`` to ``user``; returns the channels now settled (sent, failed or skipped).

    ``skip`` names channels already settled earlier. A channel the user cannot be reached on is
    never settled, so it is tried again if they add the contact detail. E-mail and texts use
    ``language`` (default: the user's own).
    """
    settled = set()
    if IN_APP not in skip:
        Notification.objects.create(user=user, kind=kind, params=params, url=url)
        _log(user, kind, IN_APP, DeliveryStatus.SENT)
        settled.add(IN_APP)
    for channel in EXTERNAL_CHANNELS:
        destination = None if channel in skip else _destination(user, channel)
        if destination is None:
            continue
        if quiet != IGNORE and in_quiet_hours(now):
            if quiet == SKIP:
                _log(user, kind, channel, DeliveryStatus.SKIPPED, "quiet_hours")
                settled.add(channel)
            continue
        _send(user, kind, channel, destination, params, url, language or user.language)
        settled.add(channel)
    return settled
