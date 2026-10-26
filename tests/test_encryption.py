from io import StringIO

import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import FieldError, ImproperlyConfigured
from django.core.management import call_command
from django.db import IntegrityError, connection
from django.test import override_settings

from apps.core.encryption import (
    DecryptionError,
    EncryptedCharField,
    blind_index,
    decrypt,
    encrypt,
)
from tests.testapp.models import Contact

OLD_KEY = Fernet.generate_key().decode()
NEW_KEY = Fernet.generate_key().decode()


def raw_column(contact, column):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {column} FROM testapp_contact WHERE id = %s", [contact.pk])  # noqa: S608
        return cursor.fetchone()[0]


def test_encrypt_decrypt_roundtrip_is_randomised():
    first, second = encrypt("০১৭১২ secret"), encrypt("০১৭১২ secret")
    assert first != second
    assert decrypt(first) == decrypt(second) == "০১৭১২ secret"


def test_decrypt_with_unknown_key_fails():
    token = encrypt("value")
    with override_settings(FIELD_ENCRYPTION_KEYS=[NEW_KEY]), pytest.raises(DecryptionError):
        decrypt(token)


def test_old_key_still_decrypts_after_rotation_is_configured():
    with override_settings(FIELD_ENCRYPTION_KEYS=[OLD_KEY]):
        token = encrypt("value")
    with override_settings(FIELD_ENCRYPTION_KEYS=[NEW_KEY, OLD_KEY]):
        assert decrypt(token) == "value"


def test_missing_keys_are_a_configuration_error():
    with override_settings(FIELD_ENCRYPTION_KEYS=[]), pytest.raises(ImproperlyConfigured):
        encrypt("value")
    with override_settings(BLIND_INDEX_KEY="short"), pytest.raises(ImproperlyConfigured):
        blind_index("value", "purpose")


@pytest.mark.django_db
def test_model_fields_store_ciphertext_and_read_plaintext():
    contact = Contact.objects.create(email="Student@Example.edu", note="private note")

    assert "Student@Example.edu" not in raw_column(contact, "email")
    assert "private note" not in raw_column(contact, "note")
    contact.refresh_from_db()
    assert contact.email == "Student@Example.edu"
    assert contact.note == "private note"


@pytest.mark.django_db
def test_null_stays_null():
    contact = Contact.objects.create(email=None)
    assert raw_column(contact, "email") is None
    assert Contact.objects.get(email__isnull=True) == contact


@pytest.mark.django_db
def test_equality_lookup_on_ciphertext_is_refused():
    with pytest.raises(FieldError):
        Contact.objects.filter(email="a@b.c").exists()


def test_unique_or_indexed_encrypted_field_is_refused():
    with pytest.raises(ImproperlyConfigured):
        EncryptedCharField(max_length=10, unique=True)


@pytest.mark.django_db
def test_rotation_command_reencrypts_with_primary_key():
    with override_settings(FIELD_ENCRYPTION_KEYS=[OLD_KEY]):
        contact = Contact.objects.create(email="a@b.c", note="note")
    with override_settings(FIELD_ENCRYPTION_KEYS=[NEW_KEY, OLD_KEY]):
        out = StringIO()
        call_command("rotate_encryption_keys", stdout=out)
    assert "testapp.Contact: 1" in out.getvalue()
    with override_settings(FIELD_ENCRYPTION_KEYS=[NEW_KEY]):
        contact.refresh_from_db()
        assert contact.email == "a@b.c"
        assert contact.note == "note"


def test_blind_index_is_deterministic_and_normalised():
    assert blind_index("  Student@Example.EDU ", "email") == blind_index(
        "student@example.edu", "email"
    )
    # NFKC: full-width "ABC123" equals plain "abc123"
    full_width = "".join(chr(0xFEE0 + ord(c)) for c in "ABC123")
    assert blind_index(full_width, "id") == blind_index("abc123", "id")
    assert len(blind_index("x", "id")) == 64


def test_blind_index_separates_purposes_and_keys():
    assert blind_index("123", "student_id") != blind_index("123", "teacher_id")
    with override_settings(BLIND_INDEX_KEY="another-blind-index-key-0123456789abcdef"):
        other = blind_index("123", "student_id")
    assert other != blind_index("123", "student_id")


def test_blind_index_of_blank_is_none():
    assert blind_index(None, "email") is None
    assert blind_index("   ", "email") is None
    with pytest.raises(ValueError):
        blind_index("x", "")


@pytest.mark.django_db
def test_blind_index_backs_a_unique_constraint():
    Contact.objects.create(email="dup@example.edu")
    Contact.objects.create(email=None)
    Contact.objects.create(email=None)
    with pytest.raises(IntegrityError):
        Contact.objects.create(email=" DUP@example.edu")
