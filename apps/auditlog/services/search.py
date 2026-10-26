"""Filtering and exporting the audit trail for the Admin (the department view is in reports)."""

import csv
import json
from collections.abc import Iterator
from datetime import datetime, time, timedelta

from django.utils import timezone

from apps.auditlog.models import AuditEvent
from apps.core.csv_safe import safe_cell

EXPORT_LIMIT = 50_000
EXPORT_COLUMNS = (
    "id",
    "date",
    "actor",
    "role",
    "action",
    "object_type",
    "object_id",
    "department_id",
    "ip",
    "request_id",
    "details",
)


def _start_of(day) -> datetime:
    return timezone.make_aware(datetime.combine(day, time.min))


def filtered(criteria: dict):
    """Events matching the cleaned ``AuditFilterForm`` data, newest first."""
    events = AuditEvent.objects.all()
    if criteria.get("actor"):
        events = events.filter(actor_username__icontains=criteria["actor"])
    if criteria.get("action"):
        events = events.filter(action=criteria["action"])
    if criteria.get("object_type"):
        events = events.filter(object_type=criteria["object_type"])
    if criteria.get("object_id"):
        events = events.filter(object_id=criteria["object_id"])
    if criteria.get("date_from"):
        events = events.filter(created_at__gte=_start_of(criteria["date_from"]))
    if criteria.get("date_to"):
        events = events.filter(created_at__lt=_start_of(criteria["date_to"] + timedelta(days=1)))
    return events.order_by("-created_at", "-pk")


def known_actions() -> list[str]:
    return sorted(AuditEvent.objects.values_list("action", flat=True).distinct())


def known_object_types() -> list[str]:
    return sorted(
        AuditEvent.objects.exclude(object_type="").values_list("object_type", flat=True).distinct()
    )


class _Echo:
    def write(self, value):
        return value


def export_lines(events) -> Iterator[str]:
    """CSV lines of at most ``EXPORT_LIMIT`` events; every cell is safe to open in a spreadsheet."""
    writer = csv.writer(_Echo())
    yield writer.writerow(EXPORT_COLUMNS)
    for event in events[:EXPORT_LIMIT].iterator(chunk_size=1000):
        yield writer.writerow(
            safe_cell(value)
            for value in (
                event.pk,
                timezone.localtime(event.created_at).isoformat(timespec="seconds"),
                event.actor_username,
                event.actor_role,
                event.action,
                event.object_type,
                event.object_id,
                event.department_id,
                event.ip,
                event.request_id,
                json.dumps(event.metadata, ensure_ascii=False, sort_keys=True),
            )
        )
