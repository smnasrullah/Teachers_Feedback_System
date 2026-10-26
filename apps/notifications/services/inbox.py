"""The bell: a user's recent notices, the unread count and marking them read.

Every query is scoped to the signed-in user, so another user's notice id is simply not found.
"""

from dataclasses import dataclass

from django.utils import timezone, translation
from django.utils.translation import get_language

from apps.notifications.models import Notification
from apps.notifications.services import delivery, messages

BELL_SIZE = 8


@dataclass(frozen=True)
class Entry:
    pk: int
    subject: str
    created_at: object
    unread: bool


def unread_count(user) -> int:
    return Notification.objects.filter(user=user, read_at__isnull=True).count()


def recent(user, limit: int = BELL_SIZE) -> list[Entry]:
    """The newest notices worded in the language the page is shown in."""
    language = get_language() or user.language
    entries = []
    with translation.override(language):
        for notice in Notification.objects.filter(user=user)[:limit]:
            text = messages.render(
                notice.kind, language, delivery.values_from_params(notice.params, notice.url)
            )
            entries.append(
                Entry(notice.pk, text.subject, notice.created_at, notice.read_at is None)
            )
    return entries


def mark_read(user, pk: int) -> Notification | None:
    """Mark one notice read; ``None`` when it does not exist or is someone else's."""
    notice = Notification.objects.filter(user=user, pk=pk).first()
    if notice is not None and notice.read_at is None:
        notice.read_at = timezone.now()
        notice.save(update_fields=["read_at"])
    return notice


def mark_all_read(user) -> None:
    Notification.objects.filter(user=user, read_at__isnull=True).update(read_at=timezone.now())
