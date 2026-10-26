"""Field-level encryption (Fernet/MultiFernet) and keyed blind indexes.

Keys come only from the environment (see settings ``FIELD_ENCRYPTION_KEYS`` and
``BLIND_INDEX_KEY``). The first encryption key encrypts; every listed key decrypts,
so a new key is rolled out by prepending it and running ``rotate_encryption_keys``.
"""

import hashlib
import hmac
import unicodedata
from functools import cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import FieldError, ImproperlyConfigured
from django.core.signals import setting_changed
from django.db import models
from django.dispatch import receiver


class DecryptionError(Exception):
    """A stored value could not be decrypted with any configured key."""


@cache
def _multi_fernet() -> MultiFernet:
    keys = settings.FIELD_ENCRYPTION_KEYS
    if not keys:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEYS must list at least one Fernet key.")
    try:
        return MultiFernet([Fernet(key) for key in keys])
    except (ValueError, TypeError) as exc:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEYS contains an invalid Fernet key.") from exc


@cache
def _blind_index_key() -> bytes:
    key = settings.BLIND_INDEX_KEY
    if not key or len(key) < 32:
        raise ImproperlyConfigured("BLIND_INDEX_KEY must be at least 32 characters.")
    return key.encode()


@receiver(setting_changed)
def _reset_key_caches(*, setting, **kwargs):
    if setting in {"FIELD_ENCRYPTION_KEYS", "BLIND_INDEX_KEY"}:
        _multi_fernet.cache_clear()
        _blind_index_key.cache_clear()


def encrypt(value: str) -> str:
    return _multi_fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _multi_fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionError(
            "Stored value could not be decrypted with the configured keys."
        ) from exc


def normalize_for_index(value: str) -> str:
    """Strip, NFKC and casefold so visually equal inputs share one index value."""
    value = unicodedata.normalize("NFKC", value)
    value = unicodedata.normalize("NFKC", value.casefold())
    return value.strip()


def blind_index(value: str | None, purpose: str) -> str | None:
    """Deterministic HMAC-SHA256 of the normalised value, domain-separated by ``purpose``.

    Returns ``None`` for ``None`` or blank input so nullable unique columns stay valid.
    """
    if not purpose:
        raise ValueError("blind_index() needs a non-empty purpose.")
    if value is None:
        return None
    normalized = normalize_for_index(value)
    if not normalized:
        return None
    purpose_key = hmac.new(_blind_index_key(), purpose.encode(), hashlib.sha256).digest()
    return hmac.new(purpose_key, normalized.encode(), hashlib.sha256).hexdigest()


class EncryptedFieldMixin:
    """Encrypts on write, decrypts on read. Ciphertext is random, so only ``isnull`` lookups
    are allowed; use a separate blind-index column for equality and uniqueness."""

    _forbidden_options = ("primary_key", "unique", "db_index")

    def __init__(self, *args, **kwargs):
        for option in self._forbidden_options:
            if kwargs.get(option):
                raise ImproperlyConfigured(
                    f"{type(self).__name__} cannot use {option}=True; index a blind_index column."
                )
        super().__init__(*args, **kwargs)

    def get_internal_type(self):
        return "TextField"

    def get_lookup(self, lookup_name):
        if lookup_name != "isnull":
            raise FieldError(
                f"{type(self).__name__} '{self.name}' supports only isnull lookups; "
                "query its blind index instead."
            )
        return super().get_lookup(lookup_name)

    def from_db_value(self, value, expression, connection):
        if value is None:
            return None
        return decrypt(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None:
            return None
        return encrypt(str(value))


class EncryptedTextField(EncryptedFieldMixin, models.TextField):
    pass


class EncryptedCharField(EncryptedFieldMixin, models.CharField):
    """``max_length`` limits the plaintext; the column itself is unbounded text."""
