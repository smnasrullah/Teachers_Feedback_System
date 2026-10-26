"""The Admin's message templates: save wording, and send a sample to check it."""

from datetime import timedelta

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.auditlog.services import audit
from apps.notifications.models import Kind, MessageTemplate
from apps.notifications.services import delivery, messages

FIELDS = ("subject_en", "body_en", "subject_bn", "body_bn")
SAMPLE_HOURS = 24


def row_for(kind: str) -> MessageTemplate | None:
    return MessageTemplate.objects.filter(kind=kind).first()


def initial(kind: str) -> dict:
    row = row_for(kind)
    return {field: getattr(row, field) for field in FIELDS} if row else {}


def save(kind: str, data: dict, *, actor, request=None) -> None:
    """Store the wording; an all-blank form removes the override so the built-in text applies."""
    values = {field: data.get(field, "") for field in FIELDS}
    with transaction.atomic():
        if any(values.values()):
            MessageTemplate.objects.update_or_create(kind=kind, defaults=values)
        else:
            MessageTemplate.objects.filter(kind=kind).delete()
        audit.record(
            "notifications.template_changed",
            request=request,
            actor=actor,
            metadata={"template": kind, "customised": [f for f in FIELDS if values[f]]},
        )


def send_test(kind: str, language: str, user, now=None) -> set[str]:
    """Send a sample of ``kind`` to ``user`` on every channel they have, quiet hours aside.
    Returns the channels used (always including the in-app notice)."""
    now = now or timezone.now()
    params = {
        "round": messages.sample("round"),
        "course": messages.sample("course"),
        "pending": 2,
        "closes_at": (now + timedelta(hours=SAMPLE_HOURS)).isoformat(),
        "hours": SAMPLE_HOURS,
    }
    return delivery.notify(
        user,
        Kind(kind),
        params,
        url=reverse("accounts:dashboard"),
        now=now,
        quiet=delivery.IGNORE,
        language=language,
    )
