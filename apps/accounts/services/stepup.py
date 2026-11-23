"""Step-up for sensitive actions: the current password again, good for ``STEP_UP_SECONDS``.

Signing in with the password counts as the first confirmation. The re-check goes through
``authenticate`` so wrong passwords count towards the same django-axes lockout as the login
form; every confirmation and refusal is audited (never with the password).
"""

import time
from enum import StrEnum

from django.conf import settings
from django.contrib.auth import authenticate

from apps.accounts.services import login as login_service
from apps.auditlog.services import audit

STEP_UP_KEY = login_service.STEP_UP_KEY


class StepUpOutcome(StrEnum):
    OK = "ok"
    REJECTED = "rejected"
    LOCKED = "locked"


def is_fresh(request) -> bool:
    confirmed_at = request.session.get(STEP_UP_KEY)
    if not isinstance(confirmed_at, int):
        return False
    return 0 <= int(time.time()) - confirmed_at <= settings.STEP_UP_SECONDS


def confirm(request, password: str) -> StepUpOutcome:
    """Check the signed-in user's password; on success sensitive actions open for a while."""
    user = request.user
    username = user.get_username()
    request.session.pop(STEP_UP_KEY, None)
    if login_service.is_locked(request, username):
        outcome = StepUpOutcome.LOCKED
    else:
        checked = authenticate(request, username=username, password=password)
        ok = checked is not None and checked.pk == user.pk
        outcome = StepUpOutcome.OK if ok else StepUpOutcome.REJECTED
    if outcome == StepUpOutcome.OK:
        login_service.mark_password_confirmed(request)
    audit.record(
        "auth.step_up",
        request=request,
        actor=user,
        department_id=user.department_id,
        metadata={"outcome": outcome.value},
    )
    return outcome
