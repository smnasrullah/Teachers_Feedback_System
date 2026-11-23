"""Account claiming: ID + activation code, then a password (and an authenticator, for a role
in ``settings.TOTP_REQUIRED_ROLES``), then the account itself.

Every failure of the first step looks the same to the caller (``find_claimable`` returns
``None``) and costs the same work, whether the ID is unknown, claimed, revoked or the code
is wrong, expired or used.

The account is created in the last step. Until then the chosen password (as its hash) and
any new TOTP secret wait in the session, encrypted.
"""

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction
from django.utils import timezone, translation

from apps.accounts.models import IdRegistry, IdType, RegistryStatus, User
from apps.accounts.services import activation, twofactor
from apps.accounts.services.username import generate_username
from apps.auditlog.services import audit
from apps.core.encryption import DecryptionError, decrypt
from apps.core.permissions import Role


class SignupError(Exception):
    """The sign-up cannot continue; the person starts again from the first step."""


def _open_for_signup(row: IdRegistry, now) -> bool:
    """Unclaimed with a live code; a claimed row's code is a password reset code instead."""
    return (
        row.status == RegistryStatus.UNCLAIMED
        and row.claimed_by_id is None
        and activation.code_is_live(row, now)
    )


def find_claimable(external_id: str, code: str) -> IdRegistry | None:
    """The unclaimed registry row this ID and unexpired unused code belong to."""
    return activation.find_row(external_id, code, _open_for_signup)


def role_for(registry: IdRegistry) -> str:
    return Role.STUDENT if registry.id_type == IdType.STUDENT else Role.TEACHER


def username_for(registry: IdRegistry) -> str:
    """A freshly issued username for the account to be."""
    return generate_username(role_for(registry))


def password_subject(registry: IdRegistry, username: str) -> User:
    """The account to be, unsaved, for the password rules: its username (similarity) and
    whether it will head a department (the stronger rule). Its teacher profile is filled in
    from the registry row, as the account has no claim to look it up by yet."""
    user = User(username=username, role=role_for(registry))
    user.__dict__["teacher_profile"] = getattr(registry, "teacher_profile", None)
    return user


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
    registry_pk: int,
    *,
    username: str,
    password_hash: str,
    secret: str | None = None,
    code: str = "",
    request=None,
) -> tuple[User, list[str]] | None:
    """Create the account; for a role that requires it, only once ``code`` from the new
    authenticator (``secret``) checks out.

    Returns the account and its recovery codes (none without an authenticator), ``None`` for
    a wrong or missing code (try again), and raises ``SignupError`` when the registry row is
    no longer open (start again). Claiming the row and burning the activation code happen in
    the same transaction.
    """
    registry = (
        IdRegistry.objects.select_for_update(of=("self",))
        .select_related("department")
        .get(pk=registry_pk)
    )
    now = timezone.now()
    if not _open_for_signup(registry, now):
        raise SignupError
    needs_authenticator = twofactor.required_for_registry(registry)
    step = twofactor.matching_step(secret, code) if needs_authenticator and secret else None
    if needs_authenticator and step is None:
        return None
    user = _new_account(registry, username)
    user.password = password_hash
    user.save(update_fields=["password"])
    codes = twofactor.activate(user, secret, step) if needs_authenticator else []
    registry.claimed_by = user
    registry.status = RegistryStatus.CLAIMED
    activation.burn(registry, now)
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
        "auth.signup",
        request=request,
        actor=user,
        target=user,
        department_id=user.department_id,
        metadata={"id_type": registry.id_type},
    )
    return user, codes
