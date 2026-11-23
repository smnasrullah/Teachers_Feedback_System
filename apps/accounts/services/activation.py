"""One-time codes on registry rows: activation codes for sign-up and reset codes for a
forgotten password. The plaintext exists only in the response that hands it over."""

import hmac
import secrets
from collections.abc import Callable

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import IdRegistry, registry_index
from apps.accounts.services.identifiers import (
    CODE_ALPHABET,
    clean_registry_id,
    normalize_activation_code,
)
from apps.core.encryption import blind_index

CODE_LENGTH = 12
GROUP_SIZE = 4
HASH_PURPOSE = "registry.activation_code"
# What a code is compared with when no registry row matched, so a miss costs the same.
_MISS = "0" * 64


def generate_code() -> str:
    """60 random bits, shown as ``XXXX-XXXX-XXXX`` (the hyphens are cosmetic)."""
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    return "-".join(raw[i : i + GROUP_SIZE] for i in range(0, CODE_LENGTH, GROUP_SIZE))


def hash_code(code: str) -> str:
    """Keyed hash of the normalised code; the key lives in the environment, not the database."""
    normalized = normalize_activation_code(code)
    if not normalized:
        raise ValueError("An activation code cannot be blank.")
    return blind_index(normalized, HASH_PURPOSE)


def code_is_live(row: IdRegistry, now) -> bool:
    """The row carries an unused, unexpired code."""
    return (
        bool(row.activation_code_hash)
        and row.activation_used_at is None
        and row.activation_expires_at is not None
        and row.activation_expires_at > now
    )


def find_row(
    external_id: str, code: str, is_open: Callable[[IdRegistry, object], bool]
) -> IdRegistry | None:
    """The registry row this ID and live code belong to, if ``is_open`` accepts it.

    Every failure (unknown ID, wrong, used or expired code, a row in the wrong state) returns
    ``None`` after the same work, so the caller can answer with one generic message.
    """
    try:
        normalized_id = clean_registry_id(external_id)
    except ValidationError:
        normalized_id = ""
    submitted = hash_code(code) if normalize_activation_code(code) else _MISS
    rows = list(IdRegistry.objects.filter(external_id_index=registry_index(normalized_id) or ""))
    now = timezone.now()
    match = None
    for row in rows or [None]:
        stored = (row.activation_code_hash if row else "") or _MISS
        same_code = hmac.compare_digest(stored, submitted)
        if same_code and row is not None and code_is_live(row, now) and is_open(row, now):
            match = row
    return match


def burn(row: IdRegistry, now) -> None:
    """Use the row's code up (the caller holds the row locked)."""
    row.activation_code_hash = ""
    row.activation_expires_at = None
    row.activation_used_at = now
