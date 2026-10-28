"""Account claiming: ID + activation code, password, authenticator, then the account itself.

Every failure of the first step looks the same to the caller (``find_claimable`` returns
``None``) and costs the same work, whether the ID is unknown, claimed, revoked or the code
is wrong, expired or used.

The account is created only when the first authenticator code checks out. Until then the
chosen password (as its hash) and the new TOTP secret wait in the session, encrypted.

A claimed row carries an activation code only after the Admin reset its access (lost phone):
the same steps then re-enrol the existing account, which keeps its username.
"""

import hmac

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone, translation

from apps.accounts.models import IdRegistry, IdType, RegistryStatus, User, registry_index
from apps.accounts.services import activation, twofactor
from apps.accounts.services.identifiers import clean_registry_id, normalize_activation_code
from apps.accounts.services.username import generate_username
from apps.auditlog.services import audit
from apps.core.encryption import DecryptionError, decrypt
from apps.core.permissions import Role

# What a code is compared with when no registry row matched, so a miss costs the same.
_MISS = "0" * 64
OPEN_STATUSES = (RegistryStatus.UNCLAIMED, RegistryStatus.CLAIMED)


class SignupError(Exception):
    """The sign-up cannot continue; the person starts again from the first step."""


def _open_for_signup(row: IdRegistry | None, now) -> bool:
    """Unclaimed (new account) or claimed after an access reset; never revoked."""
    return (
        row is not None
        and row.status in OPEN_STATUSES
        and (row.status == RegistryStatus.UNCLAIMED) == (row.claimed_by_id is None)
        and bool(row.activation_code_hash)
        and row.activation_used_at is None
        and row.activation_expires_at is not None
        and row.activation_expires_at > now
    )


def find_claimable(external_id: str, code: str) -> IdRegistry | None:
    """The open registry row this ID and unexpired unused code belong to."""
    try:
        normalized_id = clean_registry_id(external_id)
    except ValidationError:
        normalized_id = ""
    submitted = activation.hash_code(code) if normalize_activation_code(code) else _MISS
    rows = list(IdRegistry.objects.filter(external_id_index=registry_index(normalized_id) or ""))
    now = timezone.now()
    match = None
    for row in rows or [None]:
        stored = (row.activation_code_hash if row else "") or _MISS
        same_code = hmac.compare_digest(stored, submitted)
        if same_code and _open_for_signup(row, now):
            match = row
    return match


def role_for(registry: IdRegistry) -> str:
    return Role.STUDENT if registry.id_type == IdType.STUDENT else Role.TEACHER


def username_for(registry: IdRegistry) -> str:
    """The account's username: the existing one when re-enrolling, else a freshly issued one."""
    if registry.claimed_by_id:
        return registry.claimed_by.username
    return generate_username(role_for(registry))


def unseal(token: str | None) -> str | None:
    """A password hash or secret the session holds encrypted; ``None`` if absent or unreadable."""
    if not token:
        return None
    try:
        return decrypt(token)
    except DecryptionError:
        return None


def hash_password(password: str) -> str:
    return make_password(password)


def _usable_language() -> str:
    language = translation.get_language() or settings.LANGUAGE_CODE
    return language if language in dict(settings.LANGUAGES) else settings.LANGUAGE_CODE


def _new_account(registry: IdRegistry, username: str) -> User:
    try:
        with transaction.atomic():
            return User.objects.create_user(
                role_for(registry),
                None,
                username=username,
                department=registry.department,
                language=_usable_language(),
            )
    except IntegrityError:
        raise SignupError from None


@transaction.atomic
def complete(
    registry_pk: int, *, username: str, password_hash: str, secret: str, code: str, request=None
) -> tuple[User, list[str]] | None:
    """Create (or re-enrol) the account once ``code`` from the new authenticator checks out.

    Returns the account and its recovery codes, ``None`` for a wrong code (try again), and
    raises ``SignupError`` when the registry row is no longer open (start again). Claiming
    the row and burning the activation code happen in the same transaction.
    """
    step = twofactor.matching_step(secret, code)
    if step is None:
        return None
    registry = (
        IdRegistry.objects.select_for_update(of=("self",))
        .select_related("department", "claimed_by")
        .get(pk=registry_pk)
    )
    now = timezone.now()
    if not _open_for_signup(registry, now):
        raise SignupError
    reenrol = registry.claimed_by is not None
    if reenrol:
        user = User.objects.select_for_update().get(pk=registry.claimed_by_id)
        if user.username != username or not user.is_active:
            raise SignupError
    else:
        user = _new_account(registry, username)
    user.password = password_hash
    user.save(update_fields=["password"])
    codes = twofactor.activate(user, secret, step)
    registry.claimed_by = user
    registry.status = RegistryStatus.CLAIMED
    registry.activation_code_hash = ""
    registry.activation_expires_at = None
    registry.activation_used_at = now
    registry.save(
        update_fields=[
            "claimed_by",
            "status",
            "activation_code_hash",
            "activation_expires_at",
            "activation_used_at",
        ]
    )
    audit.record(
        "auth.reenrolled" if reenrol else "auth.signup",
        request=request,
        actor=user,
        target=user,
        department_id=user.department_id,
        metadata={"id_type": registry.id_type},
    )
    return user, codes
