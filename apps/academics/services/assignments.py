"""Assign teachers to many offerings at once."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.academics.models import CourseOffering
from apps.accounts.models import TeacherProfile
from apps.auditlog.services import audit


@transaction.atomic
def assign_teachers(changes: dict[int, int], *, actor, request=None) -> int:
    """Set ``offering id -> teacher profile id``; all or nothing. Returns how many changed."""
    offerings = list(CourseOffering.objects.select_for_update().filter(pk__in=changes))
    known = set(
        TeacherProfile.objects.filter(pk__in=set(changes.values())).values_list("pk", flat=True)
    )
    if len(offerings) != len(changes) or not set(changes.values()) <= known:
        raise ValidationError(_("Some offerings or teachers no longer exist."), code="stale")
    changed = [offering for offering in offerings if offering.teacher_id != changes[offering.pk]]
    for offering in changed:
        offering.teacher_id = changes[offering.pk]
    CourseOffering.objects.bulk_update(changed, ["teacher"])
    if changed:
        audit.record(
            "academics.teachers_assigned",
            request=request,
            actor=actor,
            metadata={"offerings": len(changed)},
        )
    return len(changed)
