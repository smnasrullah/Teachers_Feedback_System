"""Who may see a student's ID and full name (BLUEPRINT §5.3).

Admin: always. HOD: students of the department they head. Everyone else: never.
Querysets carry the rule too (``with_visible_ids``), so a hidden value is never even
read from the database, let alone rendered.
"""

from django.conf import settings
from django.db.models import BooleanField, Case, F, Q, Value, When

from apps.core.encryption import EncryptedCharField
from apps.core.permissions import HOD, Role, has_role

MASK = "••••••"

_ID_FIELD = EncryptedCharField(max_length=32)
_NAME_FIELD = EncryptedCharField(max_length=150)


def can_view_student_id(viewer, student_profile) -> bool:
    if has_role(viewer, Role.ADMIN):
        return True
    if has_role(viewer, HOD):
        return viewer.hod_department_id == student_profile.registry.department_id
    return False


def visible_student_id(viewer, student_profile) -> str | None:
    return (
        student_profile.registry.external_id
        if can_view_student_id(viewer, student_profile)
        else None
    )


def own_id_for_display(viewer, student_profile) -> str | None:
    """A student's own ID for their own pages: only when ``SHOW_OWN_ID_TO_STUDENT`` is on."""
    if not settings.SHOW_OWN_ID_TO_STUDENT or student_profile.registry.claimed_by_id != viewer.pk:
        return None
    return student_profile.registry.external_id


def visible_full_name(viewer, student_profile) -> str | None:
    return (
        student_profile.registry.full_name if can_view_student_id(viewer, student_profile) else None
    )


def _visibility(viewer) -> Q | None:
    """Rows of ``StudentProfile`` the viewer may identify, or ``None`` for no rows at all."""
    if has_role(viewer, Role.ADMIN):
        return Q(registry__isnull=False)
    if has_role(viewer, HOD):
        return Q(registry__department_id=viewer.hod_department_id)
    return None


def with_visible_ids(queryset, viewer):
    """Annotate ``StudentProfile`` rows with ``ids_visible``, ``visible_student_id`` and
    ``visible_full_name``. The last two are ``None`` for rows the viewer may not identify,
    and the registry's raw columns are deferred so they are never loaded."""
    condition = _visibility(viewer)
    if condition is None:
        annotations = {
            "ids_visible": Value(False, output_field=BooleanField()),
            "visible_student_id": Value(None, output_field=_ID_FIELD),
            "visible_full_name": Value(None, output_field=_NAME_FIELD),
        }
    else:
        annotations = {
            "ids_visible": Case(
                When(condition, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            ),
            "visible_student_id": Case(
                When(condition, then=F("registry__external_id")),
                default=Value(None),
                output_field=_ID_FIELD,
            ),
            "visible_full_name": Case(
                When(condition, then=F("registry__full_name")),
                default=Value(None),
                output_field=_NAME_FIELD,
            ),
        }
    return (
        queryset.select_related("registry")
        .defer("registry__external_id", "registry__full_name")
        .annotate(**annotations)
    )
