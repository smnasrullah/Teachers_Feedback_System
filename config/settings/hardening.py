"""Startup refusals for production: a missing or weak secret stops the app before it serves.

Messages name the setting, never its value (secrets must not reach logs or consoles).
"""

import base64
import binascii
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

# Values that mark a copied example file or a throwaway build value, never a real secret.
PLACEHOLDER_MARKERS = ("change-me", "changeme", "replace-me", "example", "insecure", "build-only")
MIN_SECRET_KEY_LENGTH = 50
MIN_BLIND_INDEX_KEY_LENGTH = 32
MIN_DB_PASSWORD_LENGTH = 16
# 32 random bytes almost always hold 25+ distinct values; fewer means a typed or patterned key.
MIN_DISTINCT_FERNET_BYTES = 20
REDIS_SCHEMES = ("redis", "rediss")


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def _secret_key_problems(secret_key: str) -> list[str]:
    if (
        len(secret_key) < MIN_SECRET_KEY_LENGTH
        or len(set(secret_key)) < 5
        or secret_key.startswith("django-insecure")
        or _is_placeholder(secret_key)
    ):
        return [f"DJANGO_SECRET_KEY must be random and at least {MIN_SECRET_KEY_LENGTH} chars"]
    return []


def _fernet_key_problems(keys: list[str]) -> list[str]:
    if not keys:
        return ["FIELD_ENCRYPTION_KEYS is empty"]
    for position, key in enumerate(keys, start=1):
        try:
            raw = base64.urlsafe_b64decode(key.encode())
        except (binascii.Error, ValueError):
            raw = b""
        if len(raw) != 32:
            return [f"FIELD_ENCRYPTION_KEYS key #{position} is not a Fernet key"]
        if len(set(raw)) < MIN_DISTINCT_FERNET_BYTES or _is_placeholder(key):
            return [f"FIELD_ENCRYPTION_KEYS key #{position} is weak; generate it with Fernet"]
    return []


def _blind_index_key_problems(blind_key: str, secret_key: str, fernet_keys: list[str]) -> list[str]:
    if (
        len(blind_key) < MIN_BLIND_INDEX_KEY_LENGTH
        or len(set(blind_key)) < 10
        or _is_placeholder(blind_key)
    ):
        return [f"BLIND_INDEX_KEY must be random and at least {MIN_BLIND_INDEX_KEY_LENGTH} chars"]
    if blind_key == secret_key or blind_key in fernet_keys:
        return ["BLIND_INDEX_KEY must differ from DJANGO_SECRET_KEY and FIELD_ENCRYPTION_KEYS"]
    return []


def _database_problems(database_url: str) -> list[str]:
    parts = urlsplit(database_url)
    if parts.scheme not in ("postgres", "postgresql", "pgsql"):
        return ["DATABASE_URL must point at PostgreSQL"]
    password = parts.password or ""
    if len(password) < MIN_DB_PASSWORD_LENGTH or _is_placeholder(password):
        return [f"DATABASE_URL password must be at least {MIN_DB_PASSWORD_LENGTH} random chars"]
    return []


def _host_problems(allowed_hosts: list[str], csrf_origins: list[str], site_url: str) -> list[str]:
    problems = []
    if not allowed_hosts or any(host in ("*", "") for host in allowed_hosts):
        problems.append("DJANGO_ALLOWED_HOSTS must list the site's host names (no '*')")
    if any(urlsplit(origin).scheme != "https" for origin in csrf_origins):
        problems.append("DJANGO_CSRF_TRUSTED_ORIGINS entries must start with https://")
    if urlsplit(site_url).scheme != "https":
        problems.append("SITE_URL must start with https://")
    return problems


def require_production_settings(
    *,
    secret_key: str,
    fernet_keys: list[str],
    blind_index_key: str,
    database_url: str,
    redis_urls: dict[str, str],
    allowed_hosts: list[str],
    csrf_origins: list[str],
    site_url: str,
) -> None:
    """Raise ``ImproperlyConfigured`` listing every weak or unsafe production setting."""
    problems = [
        *_secret_key_problems(secret_key),
        *_fernet_key_problems(fernet_keys),
        *_blind_index_key_problems(blind_index_key, secret_key, fernet_keys),
        *_database_problems(database_url),
        *_host_problems(allowed_hosts, csrf_origins, site_url),
    ]
    if secret_key in fernet_keys:
        problems.append("DJANGO_SECRET_KEY must differ from FIELD_ENCRYPTION_KEYS")
    problems.extend(
        f"{name} must be a redis:// or rediss:// URL"
        for name, url in redis_urls.items()
        if urlsplit(url).scheme not in REDIS_SCHEMES
    )
    if problems:
        raise ImproperlyConfigured("Production settings refused: " + "; ".join(problems) + ".")
