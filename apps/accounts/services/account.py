"""Signed-in account actions: password change, sign out everywhere, authenticator, sessions."""

import time

from django.conf import settings
from django.contrib.auth import logout, update_session_auth_hash
from django.db import transaction

from apps.accounts.models import User
from apps.accounts.services import twofactor
from apps.accounts.services.passwords import validate_account_password
from apps.auditlog.services import audit
from apps.core.encryption import DecryptionError, decrypt, encrypt
from apps.core.models import ActiveSession
from apps.core.services import sessions

# The new authenticator's secret, encrypted, while the person scans it.
DEVICE_CHANGE_KEY = "_tfs_device_change"


def active_sessions(user: User) -> list[ActiveSession]:
    """Devices signed in right now. An account has one: a new login replaces the old one."""
    return list(ActiveSession.objects.filter(user=user))


PROFILE_FIELDS = ("nickname", "language", "theme")


@transaction.atomic
def update_profile(request, user: User, data: dict) -> list[str]:
    """Save the editable profile fields and return the names that changed (audited).

    ``data`` holds the validated form values; a new ``avatar`` replaces the old file and
    ``remove_avatar`` clears it.
    """
    changed = [name for name in PROFILE_FIELDS if getattr(user, name) != data[name]]
    for name in changed:
        setattr(user, name, data[name])
    old_avatar = user.avatar.name if user.avatar else ""
    if data.get("avatar"):
        user.avatar = data["avatar"]
        changed.append("avatar")
    elif data.get("remove_avatar") and old_avatar:
        user.avatar = ""
        changed.append("avatar")
    if not changed:
        return []
    user.save(update_fields=changed)
    if "avatar" in changed and old_avatar:
        transaction.on_commit(lambda: user.avatar.storage.delete(old_avatar))
    audit.record(
        "account.profile_updated",
        request=request,
        actor=user,
        target=user,
        department_id=user.department_id,
        metadata={"changed": changed},
    )
    return changed


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


def reauthenticate(user: User, password: str, code: str) -> bool:
    """Password and a current authenticator code, both checked, before a sensitive change."""
    password_ok = user.check_password(password)
    code_ok = twofactor.verify_totp(user, code) if password_ok else False
    return password_ok and code_ok


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


def start_device_change(request) -> str:
    """Remember a new secret (encrypted, in this session) for the authenticator being set up."""
    secret = twofactor.new_secret()
    request.session[DEVICE_CHANGE_KEY] = {"secret": encrypt(secret), "at": int(time.time())}
    return secret


def pending_device_secret(request) -> str | None:
    state = request.session.get(DEVICE_CHANGE_KEY)
    if not state:
        return None
    if int(time.time()) - state.get("at", 0) > settings.SECOND_FACTOR_PENDING_SECONDS:
        request.session.pop(DEVICE_CHANGE_KEY, None)
        return None
    try:
        return decrypt(state["secret"])
    except (DecryptionError, KeyError):
        request.session.pop(DEVICE_CHANGE_KEY, None)
        return None


def finish_device_change(request, user: User, code: str) -> bool:
    """Switch to the new authenticator once a code from it checks out."""
    secret = pending_device_secret(request)
    if secret is None or not twofactor.replace_secret(user, secret, code):
        return False
    request.session.pop(DEVICE_CHANGE_KEY, None)
    sessions.mark_second_factor(request)
    audit.record(
        "auth.authenticator_changed",
        request=request,
        actor=user,
        target=user,
        department_id=user.department_id,
    )
    return True
