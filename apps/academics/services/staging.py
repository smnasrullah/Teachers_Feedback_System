"""Hold a validated upload between the preview and the confirmation.

The text is encrypted, bound to the admin who uploaded it, kept for half an hour and
consumed by the first confirmation. Nothing is written to disk.
"""

import json
import secrets

from django.core.cache import cache

from apps.core.encryption import decrypt, encrypt

TTL_SECONDS = 30 * 60


def _key(token: str) -> str:
    return f"academics.import.{token}"


def stash(user, kind: str, text: str, options: dict) -> str:
    token = secrets.token_urlsafe(24)
    payload = {"user": user.pk, "kind": kind, "text": text, "options": options}
    cache.set(_key(token), encrypt(json.dumps(payload)), TTL_SECONDS)
    return token


def take(user, kind: str, token: str) -> dict | None:
    """The stashed upload for this admin and kind, removed from the cache; else ``None``."""
    sealed = cache.get(_key(token))
    if sealed is None:
        return None
    payload = json.loads(decrypt(sealed))
    if payload["user"] != user.pk or payload["kind"] != kind:
        return None
    cache.delete(_key(token))
    return payload
