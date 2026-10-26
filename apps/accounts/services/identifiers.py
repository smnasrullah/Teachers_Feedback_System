"""Canonical forms of identifiers, applied before anything is encrypted, indexed or hashed."""

import re
import unicodedata

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
REGISTRY_ID_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9._/-]{2,31}")
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
NON_CODE_CHARS = re.compile(r"[^A-Z0-9]")


def normalize_registry_id(value: str) -> str:
    """NFKC, Bangla digits to ASCII, no whitespace, upper case (``"২১ ab"`` -> ``"21AB"``)."""
    text = unicodedata.normalize("NFKC", value).translate(BANGLA_DIGITS)
    return "".join(text.split()).upper()


def clean_registry_id(value: str) -> str:
    """Normalise and validate a student or teacher ID; raises ``ValidationError``."""
    normalized = normalize_registry_id(value)
    if not REGISTRY_ID_PATTERN.fullmatch(normalized):
        raise ValidationError(
            _("Enter an ID of 3 to 32 letters, digits, dots, slashes or hyphens."),
            code="invalid_id",
        )
    return normalized


def normalize_phone(value: str) -> str:
    """Digits only with a ``+`` and country code; a local ``01…`` number becomes ``+8801…``."""
    text = unicodedata.normalize("NFKC", value).translate(BANGLA_DIGITS).strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return ""
    if not text.startswith("+") and digits.startswith("0"):
        digits = "880" + digits[1:]
    return "+" + digits


def normalize_activation_code(value: str) -> str:
    """Upper case without separators, so ``abcd-efgh`` and ``ABCDEFGH`` are the same code."""
    return NON_CODE_CHARS.sub("", unicodedata.normalize("NFKC", value).upper())
