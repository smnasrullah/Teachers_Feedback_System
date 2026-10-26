"""Forgotten password and forgotten username, both through a code sent to the verified contact.

Looking an account up never reveals whether it exists: the lookup always runs both queries,
and an unknown or contact-less account gets a decoy challenge (see ``otp``).
"""

from axes.handlers.proxy import AxesProxyHandler
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.accounts.models import IdRegistry, OneTimeCode, OtpPurpose, User, registry_index
from apps.accounts.services import otp
from apps.accounts.services.identifiers import clean_registry_id
from apps.accounts.services.passwords import validate_account_password
from apps.auditlog.services import audit
from apps.core.models import ActiveSession


def _user_by_registry_id(external_id: str) -> User | None:
    try:
        normalized = clean_registry_id(external_id)
    except ValidationError:
        normalized = ""
    row = (
        IdRegistry.objects.filter(external_id_index=registry_index(normalized) or "")
        .select_related("claimed_by")
        .first()
    )
    return row.claimed_by if row else None


def find_account(identifier: str, *, by_username: bool) -> User | None:
    """An active account for a username or an ID; both lookups always run."""
    identifier = identifier.strip()
    named = User.objects.filter(username=identifier.lower()).first() if by_username else None
    owned = _user_by_registry_id(identifier)
    user = named or owned
    return user if user is not None and user.is_active else None


def start_password_reset(identifier: str) -> OneTimeCode:
    return otp.start_recovery(OtpPurpose.PASSWORD_RESET, find_account(identifier, by_username=True))


def start_username_recovery(external_id: str) -> OneTimeCode:
    return otp.start_recovery(
        OtpPurpose.USERNAME_RECOVERY, find_account(external_id, by_username=False)
    )


def destination_of(challenge: OneTimeCode) -> str | None:
    """Where a resend goes (``None`` for a decoy)."""
    contact = otp.contact_for(challenge.user)
    return contact.destination if contact else None


@transaction.atomic
def reset_password(challenge: OneTimeCode, new_password: str, *, request=None) -> User:
    """Set a new password after a verified code; ends every session and unlocks the account."""
    challenge = OneTimeCode.objects.select_for_update().select_related("user").get(pk=challenge.pk)
    user = challenge.user
    if not otp.is_verified(challenge) or user is None or not user.is_active:
        raise ValidationError(_("This reset link has expired. Start again."), code="expired")
    validate_account_password(new_password, user)
    user.set_password(new_password)
    user.save(update_fields=["password"])
    ActiveSession.objects.filter(user=user).delete()
    otp.consume(challenge)
    AxesProxyHandler.reset_attempts(username=user.username)
    audit.record(
        "auth.password_reset",
        request=request,
        actor=user,
        target=user,
        department_id=user.department_id,
    )
    return user


def recovered_username(challenge: OneTimeCode) -> str | None:
    """The username after a verified code (once); ``None`` if the challenge cannot give it."""
    with transaction.atomic():
        challenge = (
            OneTimeCode.objects.select_for_update().select_related("user").get(pk=challenge.pk)
        )
        if not otp.is_verified(challenge) or challenge.user is None:
            return None
        otp.consume(challenge)
        audit.record("auth.username_recovered", actor=challenge.user, target=challenge.user)
        return challenge.user.username
