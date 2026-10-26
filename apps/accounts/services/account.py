"""Signed-in account actions: password change, sign out everywhere, 2FA on/off, session list."""

from django.contrib.auth import logout, update_session_auth_hash
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.accounts.services import twofactor
from apps.accounts.services.passwords import validate_account_password
from apps.auditlog.services import audit
from apps.core.models import ActiveSession


def active_sessions(user: User) -> list[ActiveSession]:
    """Devices signed in right now. An account has one: a new login replaces the old one."""
    return list(ActiveSession.objects.filter(user=user))


def change_password(request, user: User, new_password: str) -> None:
    """Set a new password and keep only the current session signed in."""
    validate_account_password(new_password, user)
    user.set_password(new_password)
    user.save(update_fields=["password"])
    update_session_auth_hash(request, user)
    audit.record(
        "auth.password_changed",
        request=request,
        actor=user,
        target=user,
        department_id=user.department_id,
    )


def sign_out_everywhere(request, user: User) -> None:
    ActiveSession.objects.filter(user=user).delete()
    audit.record(
        "auth.sessions_revoked", request=request, actor=user, department_id=user.department_id
    )
    logout(request)


def enable_two_factor(request, user: User, code: str) -> list[str] | None:
    """Confirm the pending secret with a code; returns the recovery codes, or ``None``."""
    codes = twofactor.confirm_enrolment(user, code)
    if codes is not None:
        audit.record(
            "auth.twofactor_enabled",
            request=request,
            actor=user,
            target=user,
            department_id=user.department_id,
        )
    return codes


@transaction.atomic
def disable_two_factor(request, user: User) -> None:
    if user.requires_second_factor:
        raise ValidationError(
            _("Two-factor authentication is required for your role."), code="2fa_required"
        )
    twofactor.disable(user)
    audit.record(
        "auth.twofactor_disabled",
        request=request,
        actor=user,
        target=user,
        department_id=user.department_id,
    )


def regenerate_recovery_codes(request, user: User) -> list[str]:
    codes = twofactor.regenerate_recovery_codes(user)
    audit.record(
        "auth.recovery_codes_regenerated",
        request=request,
        actor=user,
        target=user,
        department_id=user.department_id,
    )
    return codes
