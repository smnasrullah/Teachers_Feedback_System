"""Forgotten password: the username plus an authenticator code (or a recovery code).

The answer never reveals whether an account exists: an unknown username, a disabled account
and a wrong code all fail the same way and count towards the same django-axes lockout. A
forgotten username cannot be recovered without signing in; the department or Admin looks it
up, and it is shown on the account page.
"""

import time

from axes.handlers.proxy import AxesProxyHandler
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.accounts.services import login as login_service
from apps.accounts.services import twofactor
from apps.accounts.services.passwords import validate_account_password
from apps.auditlog.services import audit
from apps.core.models import ActiveSession

# Which account passed the code check, and when; the new password must follow soon.
RESET_KEY = "_tfs_password_reset"


def find_account(username: str) -> User | None:
    user = User.objects.filter(username=username.strip().lower()).first()
    return user if user is not None and user.is_active else None


def verify(request, username: str, code: str) -> User | None:
    """The account if ``code`` is its current authenticator code or an unused recovery code."""
    user = find_account(username)
    result = twofactor.check_second_factor(user, code)
    if not result.ok:
        return None
    if result.recovery:
        login_service.record_recovery_use(request, user, result.recovery_left)
    request.session[RESET_KEY] = {"user": user.pk, "at": int(time.time())}
    return user


def pending_user(request) -> User | None:
    state = request.session.get(RESET_KEY)
    if not state:
        return None
    if int(time.time()) - state.get("at", 0) > settings.SECOND_FACTOR_PENDING_SECONDS:
        request.session.pop(RESET_KEY, None)
        return None
    return User.objects.filter(pk=state["user"], is_active=True).first()


@transaction.atomic
def reset_password(request, user: User, new_password: str) -> User:
    """Set a new password; ends every session and unlocks the account."""
    user = User.objects.select_for_update().get(pk=user.pk)
    if not user.is_active or not user.totp_enabled:
        raise ValidationError(_("This reset has expired. Start again."), code="expired")
    validate_account_password(new_password, user)
    user.set_password(new_password)
    user.save(update_fields=["password"])
    ActiveSession.objects.filter(user=user).delete()
    request.session.pop(RESET_KEY, None)
    AxesProxyHandler.reset_attempts(username=user.username)
    audit.record(
        "auth.password_reset",
        request=request,
        actor=user,
        target=user,
        department_id=user.department_id,
    )
    return user
