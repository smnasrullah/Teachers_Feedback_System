"""Unique, non-guessable, immutable usernames such as ``stu_k7x9a2``."""

import secrets

from django.apps import apps
from django.conf import settings

from apps.core.permissions import Role

PREFIXES = {Role.STUDENT: "stu", Role.TEACHER: "tch", Role.ADMIN: "adm"}
# No 0/o, 1/l/i: a username is read aloud and typed on phones.
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
SUFFIX_LENGTH = 6
MAX_ATTEMPTS = 20


def generate_username(role: str) -> str:
    """A fresh username for ``role``. The unique column still guards a concurrent duplicate."""
    try:
        prefix = PREFIXES[role]
    except KeyError:
        raise ValueError(f"No username prefix for role {role!r}.") from None
    user_model = apps.get_model(settings.AUTH_USER_MODEL)
    for _attempt in range(MAX_ATTEMPTS):
        suffix = "".join(secrets.choice(ALPHABET) for _ in range(SUFFIX_LENGTH))
        candidate = f"{prefix}_{suffix}"
        if not user_model.objects.filter(username=candidate).exists():
            return candidate
    raise RuntimeError("Could not find a free username.")
