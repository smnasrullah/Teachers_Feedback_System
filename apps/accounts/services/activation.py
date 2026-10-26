"""One-time activation codes. The plaintext exists only in the response that hands it over."""

import secrets

from apps.accounts.services.identifiers import CODE_ALPHABET, normalize_activation_code
from apps.core.encryption import blind_index

CODE_LENGTH = 12
GROUP_SIZE = 4
HASH_PURPOSE = "registry.activation_code"


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
