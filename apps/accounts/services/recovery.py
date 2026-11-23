"""Forgotten password: the registry ID plus a one-time reset code from the Admin or the head of
the person's department (``registry.issue_reset_code``). No e-mail, no authenticator.

The answer never reveals whether an account exists: an unknown ID, an unclaimed or revoked
entry, a disabled account and a wrong, used or expired code all fail the same way. The code is
checked again and burned in the same transaction that sets the new password, so it works once.
A forgotten username cannot be recovered without signing in; the department or Admin looks it
up, and it is shown on the account page.
"""

import time

from axes.handlers.proxy import AxesProxyHandler
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import IdRegistry, RegistryStatus, User
from apps.accounts.services import activation, twofactor
from apps.accounts.services.identifiers import normalize_registry_id
from apps.accounts.services.passwords import validate_account_password
from apps.auditlog.services import audit
from apps.core.encryption import blind_index
from apps.core.models import ActiveSession

# Which registry row passed the code check, and when; the new password must follow soon.
RESET_KEY = "_tfs_password_reset"
LOCKOUT_PURPOSE = "auth.reset_subject"


def lockout_subject(registry_id: str) -> str:
    """The name failed reset attempts are counted under: a keyed hash, never the ID itself."""
    return "reset:" + (blind_index(normalize_registry_id(registry_id), LOCKOUT_PURPOSE) or "-")


def _open_for_reset(row: IdRegistry, now) -> bool:
    return (
        row.status == RegistryStatus.CLAIMED
        and row.claimed_by_id is not None
        and User.objects.filter(pk=row.claimed_by_id, is_active=True).exists()
    )


def verify(request, registry_id: str, code: str) -> User | None:
    """The account if ``code`` is the live reset code of this ID's claimed entry."""
    row = activation.find_row(registry_id, code, _open_for_reset)
    if row is None:
        return None
    request.session[RESET_KEY] = {"registry": row.pk, "at": int(time.time())}
    return row.claimed_by


def _pending_registry_pk(request) -> int | None:
    state = request.session.get(RESET_KEY)
    if not state:
        return None
    if int(time.time()) - state.get("at", 0) > settings.SECOND_FACTOR_PENDING_SECONDS:
        request.session.pop(RESET_KEY, None)
        return None
    return state.get("registry")


def pending_user(request) -> User | None:
    pk = _pending_registry_pk(request)
    if pk is None:
        return None
    return User.objects.filter(registry__pk=pk, is_active=True).first()


@transaction.atomic
def reset_password(request, new_password: str) -> User:
    """Set a new password with the checked reset code and use the code up.

    Every session of the account ends, its lockout is lifted and any stored authenticator is
    forgotten (a role that requires one enrols again at the next login).
    """
    expired = ValidationError(_("This reset has expired. Start again."), code="expired")
    pk = _pending_registry_pk(request)
    row = (
        IdRegistry.objects.select_for_update(of=("self",)).filter(pk=pk).first()
        if pk is not None
        else None
    )
    now = timezone.now()
    if row is None or not activation.code_is_live(row, now) or not _open_for_reset(row, now):
        request.session.pop(RESET_KEY, None)
        raise expired
    user = User.objects.select_for_update().get(pk=row.claimed_by_id)
    validate_account_password(new_password, user)
    user.set_password(new_password)
    user.save(update_fields=["password"])
    twofactor.clear(user)
    activation.burn(row, now)
    row.save(update_fields=["activation_code_hash", "activation_expires_at", "activation_used_at"])
    ActiveSession.objects.filter(user=user).delete()
    request.session.pop(RESET_KEY, None)
    AxesProxyHandler.reset_attempts(username=user.username)
    audit.record(
        "auth.password_reset",
        request=request,
        actor=user,
        target=user,
        department_id=user.department_id,
        metadata={"via": "reset_code", "registry_id": row.pk},
    )
    return user
