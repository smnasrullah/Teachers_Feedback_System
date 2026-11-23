"""Create, edit, revoke and re-activate ID registry entries; issue activation and reset codes.

Every change is audited with row ids and counts only: never an ID, a name or a code.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import (
    IdRegistry,
    IdType,
    RegistryStatus,
    StudentProfile,
    TeacherProfile,
    registry_index,
)
from apps.accounts.services import activation
from apps.accounts.services.identifiers import clean_registry_id, normalize_registry_id
from apps.auditlog.services import audit
from apps.core.models import ActiveSession
from apps.core.permissions import HOD, Role, has_role

PROFILE_MODELS = {IdType.STUDENT: StudentProfile, IdType.TEACHER: TeacherProfile}
MAX_BULK_ROWS = 2000


@dataclass(frozen=True)
class IssuedCode:
    registry: IdRegistry
    code: str


def id_is_taken(id_type: str, external_id: str, *, exclude_pk: int | None = None) -> bool:
    matches = IdRegistry.objects.filter(
        id_type=id_type, external_id_index=registry_index(external_id)
    )
    return matches.exclude(pk=exclude_pk).exists()


def _duplicate_error() -> ValidationError:
    return ValidationError(_("This ID is already registered."), code="duplicate_id")


def _assign(instance, values: dict) -> list[str]:
    """Set the given attributes and return the names that actually changed."""
    changed = []
    for name, value in values.items():
        if getattr(instance, name) != value:
            setattr(instance, name, value)
            changed.append(name)
    return changed


def _audit_department(rows) -> int | None:
    departments = {row.department_id for row in rows}
    return departments.pop() if len(departments) == 1 else None


@transaction.atomic
def register(
    id_type: str,
    *,
    external_id: str,
    full_name: str,
    department,
    profile: dict,
    actor,
    request=None,
) -> IdRegistry:
    """Create the registry row and its profile together (both exist before signup)."""
    external_id = clean_registry_id(external_id)
    if id_is_taken(id_type, external_id):
        raise _duplicate_error()
    try:
        with transaction.atomic():
            registry = IdRegistry.objects.create(
                id_type=id_type,
                external_id=external_id,
                full_name=full_name or None,
                department=department,
            )
    except IntegrityError:
        raise _duplicate_error() from None
    PROFILE_MODELS[id_type].objects.create(registry=registry, **profile)
    audit.record(
        "registry.created",
        request=request,
        actor=actor,
        target=registry,
        department_id=department.pk,
        metadata={"id_type": id_type},
    )
    return registry


@transaction.atomic
def update(
    registry: IdRegistry,
    *,
    external_id: str,
    full_name: str,
    department,
    profile: dict,
    actor,
    request=None,
) -> list[str]:
    """Edit an entry; returns the names of the fields that changed."""
    registry = IdRegistry.objects.select_for_update().get(pk=registry.pk)
    external_id = clean_registry_id(external_id)
    if external_id != registry.external_id:
        if registry.claimed_by_id:
            raise ValidationError(
                _("The ID of a claimed entry cannot be changed."), code="claimed_id"
            )
        if id_is_taken(registry.id_type, external_id, exclude_pk=registry.pk):
            raise _duplicate_error()
    changed = _assign(
        registry,
        {"external_id": external_id, "full_name": full_name or None, "department": department},
    )
    try:
        with transaction.atomic():
            registry.save()
    except IntegrityError:
        raise _duplicate_error() from None
    owner = registry.claimed_by
    if owner is not None and owner.department_id != department.pk:
        owner.department = department
        owner.save(update_fields=["department"])
    entry = PROFILE_MODELS[registry.id_type].objects.get(registry=registry)
    new_photo = profile.get("photo")
    if new_photo and entry.photo:
        entry.photo.delete(save=False)
    changed += _assign(entry, {name: value for name, value in profile.items() if name != "photo"})
    if new_photo:
        entry.photo = new_photo
        changed.append("photo")
    entry.save()
    if changed:
        audit.record(
            "registry.updated",
            request=request,
            actor=actor,
            target=registry,
            department_id=department.pk,
            metadata={"fields": sorted(changed)},
        )
    return changed


def _locked(registries) -> list[IdRegistry]:
    rows = list(
        registries.select_related("claimed_by", "department")
        .select_for_update(of=("self",))
        .order_by("pk")
    )
    if len(rows) > MAX_BULK_ROWS:
        raise ValidationError(
            _("Select at most %(max)d entries at a time."),
            code="too_many",
            params={"max": MAX_BULK_ROWS},
        )
    return rows


@transaction.atomic
def revoke(registries, *, actor, request=None) -> int:
    """Block signup with these IDs, void their codes, and sign out and lock any account."""
    rows = [row for row in _locked(registries) if row.status != RegistryStatus.REVOKED]
    if any(row.claimed_by_id == actor.pk for row in rows):
        raise ValidationError(_("You cannot revoke your own entry."), code="revoke_self")
    for row in rows:
        row.status = RegistryStatus.REVOKED
        row.activation_code_hash = ""
        row.activation_expires_at = None
        row.save(update_fields=["status", "activation_code_hash", "activation_expires_at"])
        if row.claimed_by is not None:
            row.claimed_by.is_active = False
            row.claimed_by.save(update_fields=["is_active"])
            ActiveSession.objects.filter(user=row.claimed_by).delete()
    if rows:
        audit.record(
            "registry.revoked",
            request=request,
            actor=actor,
            department_id=_audit_department(rows),
            metadata={"count": len(rows), "registry_ids": [row.pk for row in rows]},
        )
    return len(rows)


@transaction.atomic
def activate(registries, *, actor, request=None) -> int:
    """Undo a revocation: the entry returns to claimed (account re-enabled) or unclaimed."""
    rows = [row for row in _locked(registries) if row.status == RegistryStatus.REVOKED]
    for row in rows:
        owner = row.claimed_by
        row.status = RegistryStatus.CLAIMED if owner is not None else RegistryStatus.UNCLAIMED
        row.save(update_fields=["status"])
        if owner is not None:
            owner.is_active = True
            owner.save(update_fields=["is_active"])
    if rows:
        audit.record(
            "registry.activated",
            request=request,
            actor=actor,
            department_id=_audit_department(rows),
            metadata={"count": len(rows), "registry_ids": [row.pk for row in rows]},
        )
    return len(rows)


def can_issue_reset_code(account, actor) -> bool:
    """Admin: any active student or teacher account (HODs included) with a live claim. HOD: the
    same, within the department they head (the ``StudentIdPolicy`` scope). Never oneself."""
    registry = getattr(account, "registry", None)
    if (
        account.pk == actor.pk
        or registry is None
        or registry.status != RegistryStatus.CLAIMED
        or not account.is_active
    ):
        return False
    if has_role(actor, Role.ADMIN):
        return True
    return has_role(actor, HOD) and registry.department_id == actor.hod_department_id


def _new_code(row: IdRegistry, expires_at) -> str:
    code = activation.generate_code()
    row.activation_code_hash = activation.hash_code(code)
    row.activation_expires_at = expires_at
    row.activation_used_at = None
    row.save(update_fields=["activation_code_hash", "activation_expires_at", "activation_used_at"])
    return code


def resettable_account(external_id: str, actor):
    """The account behind this ID if ``actor`` may issue it a reset code, else ``None``.

    Out of scope and unknown look the same, so a HOD learns nothing about other departments.
    """
    index = registry_index(normalize_registry_id(external_id)) or ""
    for row in IdRegistry.objects.select_related("claimed_by").filter(external_id_index=index):
        if row.claimed_by is not None and can_issue_reset_code(row.claimed_by, actor):
            return row.claimed_by
    return None


@transaction.atomic
def issue_reset_code(account, *, actor, request=None) -> IssuedCode:
    """A forgotten password: a one-time code, valid ``RESET_CODE_HOURS``, replacing any earlier.

    The person enters their ID and this code on the "Forgot password?" page and chooses a new
    password. Their current password keeps working until then. Only the keyed hash is stored;
    the plaintext exists only in the returned value.
    """
    row = (
        IdRegistry.objects.select_for_update(of=("self",))
        .select_related("claimed_by", "department")
        .filter(claimed_by=account)
        .first()
    )
    if row is None or not can_issue_reset_code(row.claimed_by, actor):
        raise ValidationError(
            _("A reset code cannot be issued for this account."), code="not_resettable"
        )
    expires_at = timezone.now() + timedelta(hours=settings.RESET_CODE_HOURS)
    code = _new_code(row, expires_at)
    audit.record(
        "account.reset_code_issued",
        request=request,
        actor=actor,
        target=row.claimed_by,
        department_id=row.department_id,
        metadata={"valid_hours": settings.RESET_CODE_HOURS, "registry_id": row.pk},
    )
    return IssuedCode(row, code)


@transaction.atomic
def issue_activation_codes(registries, *, valid_days: int, actor, request=None) -> list[IssuedCode]:
    """Give every unclaimed entry a new code (replacing any earlier one).

    Only the keyed hash is stored. The returned plaintext must be handed over in the same
    response and never kept.
    """
    rows = [row for row in _locked(registries) if row.status == RegistryStatus.UNCLAIMED]
    expires_at = timezone.now() + timedelta(days=valid_days)
    issued = []
    for row in rows:
        issued.append(IssuedCode(row, _new_code(row, expires_at)))
    if rows:
        audit.record(
            "registry.codes_issued",
            request=request,
            actor=actor,
            department_id=_audit_department(rows),
            metadata={
                "count": len(rows),
                "valid_days": valid_days,
                "registry_ids": [row.pk for row in rows],
            },
        )
    return issued
