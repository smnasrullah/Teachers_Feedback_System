"""Proxy-submission defences (BLUEPRINT §5.4): a fresh password re-check before submitting,
rate limits on re-checks and submissions, and an audit trail of both.

The re-check goes through ``authenticate`` so wrong passwords count towards the same
django-axes lockout as the login form.
"""

import time
from enum import StrEnum

from django.contrib.auth import authenticate
from django_ratelimit.core import is_ratelimited

from apps.accounts.services import login as login_service
from apps.auditlog.services import audit

REAUTH_KEY = "_tfs_feedback_reauth_at"
REAUTH_MAX_AGE = 5 * 60
# (ratelimit key, rate): per account and per address; a campus NAT shares one address.
REAUTH_RATES = (("user", "10/10m"), ("ip", "100/10m"))
SUBMIT_RATES = (("user", "20/10m"), ("ip", "300/10m"))


class ReauthOutcome(StrEnum):
    OK = "ok"
    REJECTED = "rejected"
    LOCKED = "locked"
    THROTTLED = "throttled"


def _throttled(request, group: str, rates) -> bool:
    # Every limit counts every attempt, so no limit can be dodged by tripping another first.
    hits = [
        is_ratelimited(request, group=f"{group}.{key}", key=key, rate=rate, increment=True)
        for key, rate in rates
    ]
    return any(hits)


def reauthenticate(request, password: str) -> ReauthOutcome:
    """Re-check the signed-in user's password; on success submitting is allowed for
    ``REAUTH_MAX_AGE`` seconds."""
    user = request.user
    username = user.get_username()
    request.session.pop(REAUTH_KEY, None)
    if _throttled(request, "feedback.reauth", REAUTH_RATES):
        outcome = ReauthOutcome.THROTTLED
    elif login_service.is_locked(request, username):
        outcome = ReauthOutcome.LOCKED
    else:
        checked = authenticate(request, username=username, password=password)
        outcome = (
            ReauthOutcome.OK
            if checked is not None and checked.pk == user.pk
            else ReauthOutcome.REJECTED
        )
    if outcome == ReauthOutcome.OK:
        request.session[REAUTH_KEY] = int(time.time())
    audit.record(
        "feedback.reauth",
        request=request,
        department_id=user.department_id,
        metadata={"outcome": outcome.value},
    )
    return outcome


def reauth_is_fresh(request) -> bool:
    checked_at = request.session.get(REAUTH_KEY)
    if not isinstance(checked_at, int):
        return False
    return 0 <= int(time.time()) - checked_at <= REAUTH_MAX_AGE


def submit_throttled(request) -> bool:
    """Count one submission attempt; ``True`` (and audited) when a limit is exceeded."""
    throttled = _throttled(request, "feedback.submit", SUBMIT_RATES)
    if throttled:
        audit.record(
            "feedback.submit_throttled", request=request, department_id=request.user.department_id
        )
    return throttled
