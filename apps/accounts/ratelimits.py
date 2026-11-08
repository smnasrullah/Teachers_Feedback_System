"""Rate limits keyed by IP and by the thing being guessed (an ID, a username, a challenge).

Both limits apply to every attempt, valid or not, so a limit trips identically for known and
unknown IDs. The view reads ``request.limited`` and answers 429 without doing the work.
"""

from django.conf import settings
from django_ratelimit.decorators import ratelimit

from apps.accounts.services.identifiers import normalize_registry_id
from apps.core.encryption import blind_index
from apps.core.net import client_ip
from apps.core.services.demo import constants as demo

PURPOSE = "ratelimit.subject"


def _hashed(value: str) -> str:
    return blind_index(value, PURPOSE) or "-"


def registry_id(group, request) -> str:
    return _hashed("id:" + normalize_registry_id(request.POST.get("registry_id", "")))


def username(group, request) -> str:
    username = request.POST.get("username", "").strip().lower()
    if settings.PUBLIC_DEMO_ENABLED and username in demo.USERNAMES:
        # These credentials are intentionally shared publicly. Keep the subject bucket per
        # visitor IP so one tester cannot exhaust every other visitor's demo login attempts.
        return _hashed(f"user:{username}:ip:{client_ip(request)}")
    return _hashed("user:" + username)


def identifier(group, request) -> str:
    return _hashed("ident:" + normalize_registry_id(request.POST.get("identifier", "")))


def session_subject(group, request) -> str:
    """The browser session working through a multi-step flow."""
    return _hashed(f"session:{request.session.session_key or client_ip(request)}")


def limited(subject_key, *, ip_rate: str = "30/10m", subject_rate: str = "8/15m"):
    """Per-IP and per-subject limits on POST; sets ``request.limited`` instead of blocking."""

    def decorator(view):
        view = ratelimit(key=subject_key, rate=subject_rate, method="POST", block=False)(view)
        return ratelimit(key="ip", rate=ip_rate, method="POST", block=False)(view)

    return decorator
