"""Session lifetime rules: single active session, idle timeout, absolute timeout."""

import secrets
import time
from enum import StrEnum

from django.conf import settings
from django.utils import timezone

from apps.core.models import ActiveSession
from apps.core.net import UNKNOWN_IP, client_ip

LOGIN_ID_KEY = "_tfs_login_id"
AUTH_AT_KEY = "_tfs_auth_at"
SEEN_AT_KEY = "_tfs_seen_at"
# Set when this login passed a second factor (TOTP or recovery code).
SECOND_FACTOR_KEY = "_tfs_second_factor_at"
# Set when this login signed another device out: when that device had signed in (epoch seconds).
NEW_DEVICE_KEY = "_tfs_replaced_device_at"
# Set at login: the person's saved language, waiting to become this browser's language cookie.
LANGUAGE_KEY = "_tfs_saved_language"
MAX_USER_AGENT = 255
# Write the last-seen time at most this often to avoid a session save on every request.
SEEN_AT_RESOLUTION = 60


class SessionProblem(StrEnum):
    IDLE = "idle"
    EXPIRED = "expired"
    REPLACED = "replaced"
    SECOND_FACTOR = "second_factor"


def start(request, user) -> None:
    """Bind this login as the user's only active session (called on ``user_logged_in``)."""
    login_id = secrets.token_hex(32)
    now = int(time.time())
    request.session[LOGIN_ID_KEY] = login_id
    request.session[AUTH_AT_KEY] = now
    request.session[LANGUAGE_KEY] = user.language
    request.session[SEEN_AT_KEY] = now
    ip = client_ip(request)
    device = {
        "ip": None if ip == UNKNOWN_IP else ip,
        "user_agent": request.META.get("HTTP_USER_AGENT", "")[:MAX_USER_AGENT],
    }
    previous = ActiveSession.objects.filter(user=user).first()
    if previous is not None and (previous.ip, previous.user_agent) != tuple(device.values()):
        request.session[NEW_DEVICE_KEY] = int(previous.created_at.timestamp())
    ActiveSession.objects.update_or_create(
        user=user, defaults={"login_id": login_id, "created_at": timezone.now(), **device}
    )


def pop_replaced_device(request) -> int | None:
    """When the device this login signed out had signed in, once; ``None`` if there was none."""
    return request.session.pop(NEW_DEVICE_KEY, None)


def mark_second_factor(request) -> None:
    request.session[SECOND_FACTOR_KEY] = int(time.time())


def end(request, user) -> None:
    """Forget the active-session binding if it belongs to this session (``user_logged_out``)."""
    login_id = request.session.get(LOGIN_ID_KEY)
    if user is not None and login_id:
        ActiveSession.objects.filter(user=user, login_id=login_id).delete()


def problem(request) -> SessionProblem | None:
    """Why the authenticated session must end, or ``None`` if it may continue."""
    session = request.session
    now = int(time.time())
    auth_at = session.get(AUTH_AT_KEY)
    seen_at = session.get(SEEN_AT_KEY)
    login_id = session.get(LOGIN_ID_KEY)
    if not (auth_at and seen_at and login_id):
        return SessionProblem.EXPIRED
    if now - auth_at > settings.SESSION_ABSOLUTE_TIMEOUT:
        return SessionProblem.EXPIRED
    if now - seen_at > settings.SESSION_IDLE_TIMEOUT:
        return SessionProblem.IDLE
    active = (
        ActiveSession.objects.filter(user_id=request.user.pk)
        .values_list("login_id", flat=True)
        .first()
    )
    if active is None or not secrets.compare_digest(active, login_id):
        return SessionProblem.REPLACED
    # Fail closed: accounts that see student identities never keep a session that skipped TOTP
    # (for example one opened before the account was promoted).
    if not session.get(SECOND_FACTOR_KEY) and request.user.requires_second_factor:
        return SessionProblem.SECOND_FACTOR
    return None


def touch(request) -> None:
    now = int(time.time())
    if now - request.session.get(SEEN_AT_KEY, 0) >= SEEN_AT_RESOLUTION:
        request.session[SEEN_AT_KEY] = now
