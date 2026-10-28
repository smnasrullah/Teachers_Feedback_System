"""Create, edit, revoke and re-activate ID registry entries, issue activation codes, reset access.

Every change is audited with row ids and counts only: never an ID, a name or a code.
"""

from dataclasses import dataclass
from datetime import timedelta

from axes.handlers.proxy import AxesProxyHandler
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
from apps.accounts.services import activation, twofactor
from apps.accounts.services.identifiers import clean_registry_id
from apps.auditlog.services import audit
from apps.core.models import ActiveSession

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


def can_reset_access(account, actor) -> bool:
    """Students and teachers (HODs included) with a live claim; never the Admin's own account."""
    registry = getattr(account, "registry", None)
    return (
        account.pk != actor.pk
        and registry is not None
        and registry.status == RegistryStatus.CLAIMED
        and account.is_active
    )


def _new_code(row: IdRegistry, expires_at) -> str:
    code = activation.generate_code()
    row.activation_code_hash = activation.hash_code(code)
    row.activation_expires_at = expires_at
    row.activation_used_at = None
    row.save(update_fields=["activation_code_hash", "activation_expires_at", "activation_used_at"])
    return code


@transaction.atomic
def reset_access(account, *, valid_days: int, actor, request=None) -> IssuedCode:
    """Lost phone: clear the password and authenticator, end every session, issue a new code.

    The person then signs up again with their ID and this code; the same steps re-enrol the
    existing account (same username, same history). The plaintext code exists only in the
    returned value.
    """
    row = (
        IdRegistry.objects.select_for_update(of=("self",))
        .select_related("claimed_by", "department")
        .filter(claimed_by=account)
        .first()
    )
    if row is None or not can_reset_access(row.claimed_by, actor):
        raise ValidationError(_("Access to this account cannot be reset."), code="not_resettable")
    user = row.claimed_by
    user.set_unusable_password()
    user.save(update_fields=["password"])
    twofactor.clear(user)
    ActiveSession.objects.filter(user=user).delete()
    AxesProxyHandler.reset_attempts(username=user.username)
    code = _new_code(row, timezone.now() + timedelta(days=valid_days))
    audit.record(
        "account.access_reset",
        request=request,
        actor=actor,
        target=user,
        department_id=row.department_id,
        metadata={"valid_days": valid_days, "registry_id": row.pk},
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
