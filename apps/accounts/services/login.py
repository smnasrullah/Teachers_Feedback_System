"""Password login with an optional or mandatory second factor, kept as pending state.

A correct password alone never signs anyone in when the account uses TOTP: the user is
held in the session as *pending* until the code (or a recovery code) checks out, so
nothing authenticated exists in between. Failures are audited by hash, never by name.
"""

import time
from enum import StrEnum

from axes.handlers.proxy import AxesProxyHandler
from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.signals import user_login_failed
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from apps.accounts.models import User
from apps.auditlog.services import audit
from apps.core.encryption import blind_index
from apps.core.permissions import HOD, Role, primary_role
from apps.core.services import sessions

PENDING_KEY = "_tfs_pending_login"
MODEL_BACKEND = "django.contrib.auth.backends.ModelBackend"
USERNAME_PURPOSE = "audit.username"
DASHBOARDS = {
    Role.ADMIN.value: "accounts:dashboard_admin",
    HOD: "accounts:dashboard_hod",
    Role.TEACHER.value: "accounts:dashboard_teacher",
    Role.STUDENT.value: "accounts:dashboard_student",
}


class NextStep(StrEnum):
    DONE = "done"
    CODE = "code"
    ENROL = "enrol"


def username_ref(username: str) -> str:
    """A non-reversible reference for audit rows (a typed name may even be a password)."""
    return blind_index(username.strip().lower(), USERNAME_PURPOSE) or ""


def next_step(user: User) -> NextStep:
    if user.totp_enabled:
        return NextStep.CODE
    return NextStep.ENROL if user.requires_second_factor else NextStep.DONE


def begin_pending(request, user: User, next_url: str | None = None) -> None:
    request.session[PENDING_KEY] = {"user": user.pk, "at": int(time.time()), "next": next_url or ""}


def pending_next(request) -> str | None:
    return request.session.get(PENDING_KEY, {}).get("next") or None


def pending_user(request) -> User | None:
    state = request.session.get(PENDING_KEY)
    if not state:
        return None
    if int(time.time()) - state.get("at", 0) > settings.SECOND_FACTOR_PENDING_SECONDS:
        request.session.pop(PENDING_KEY, None)
        return None
    return User.objects.filter(pk=state["user"], is_active=True).first()


def complete_login(request, user: User, *, second_factor: bool) -> None:
    login(request, user, backend=MODEL_BACKEND)
    request.session.pop(PENDING_KEY, None)
    if second_factor:
        sessions.mark_second_factor(request)
    audit.record(
        "auth.login",
        request=request,
        actor=user,
        department_id=user.department_id,
        metadata={"second_factor": second_factor},
    )


def landing_url(user: User) -> str:
    return reverse(DASHBOARDS.get(primary_role(user), "core:home"))


def safe_next(request) -> str | None:
    target = request.POST.get("next") or request.GET.get("next") or ""
    allowed = url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    )
    return target if target and allowed else None


def is_locked(request, username: str) -> bool:
    return not AxesProxyHandler.is_allowed(request, {"username": username})


def note_failure(request, username: str, *, stage: str) -> None:
    """Audit a failed attempt (by hash, same work whether the account exists or not).

    Password failures reach django-axes through ``authenticate``; a wrong second-factor
    code is reported to it here so it counts towards the same lockout.
    """
    if stage != "password":
        user_login_failed.send(sender=User, credentials={"username": username}, request=request)
    audit.record(
        "auth.login_failed",
        request=request,
        metadata={"stage": stage, "username_ref": username_ref(username)},
    )


def record_recovery_use(request, user: User, left: int) -> None:
    audit.record(
        "auth.recovery_code_used",
        request=request,
        actor=user,
        target=user,
        department_id=user.department_id,
        metadata={"remaining": left},
    )


def record_lockout(sender, request, username, **kwargs) -> None:
    """Receiver for django-axes' ``user_locked_out`` signal (connected in ``AccountsConfig``)."""
    audit.record(
        "auth.lockout", request=request, metadata={"username_ref": username_ref(username or "")}
    )
