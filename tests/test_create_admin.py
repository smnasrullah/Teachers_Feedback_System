from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.utils import translation

from apps.accounts.models import User
from apps.accounts.services.passwords import validate_strong_password
from apps.auditlog.models import AuditEvent
from apps.core.csv_safe import safe_cell
from apps.core.permissions import Role

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def english():
    """The command speaks the site language (Bangla); these tests match English wording."""
    with translation.override("en"):
        yield


COMMAND = "apps.accounts.management.commands.create_admin"
STRONG = "Correct-Horse-Battery-9"


def run(monkeypatch, emails, passwords):
    monkeypatch.setattr("builtins.input", lambda _prompt: next(emails))
    monkeypatch.setattr(f"{COMMAND}.getpass", lambda _prompt: next(passwords))
    out, err = StringIO(), StringIO()
    call_command("create_admin", stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


def test_creates_an_admin_with_a_generated_username(monkeypatch):
    out, _err = run(monkeypatch, iter(["boss@example.edu"]), iter([STRONG, STRONG]))
    admin = User.objects.get()
    assert admin.role == Role.ADMIN
    assert admin.username.startswith("adm_") and admin.username in out
    assert admin.check_password(STRONG)
    assert admin.password.startswith("argon2$argon2id$")
    assert admin.contact_email == "boss@example.edu"
    assert admin.totp_enabled is False  # enrolled at the first login
    assert STRONG not in out
    event = AuditEvent.objects.get(action="admin.created")
    assert event.object_id == str(admin.pk)
    assert STRONG not in str(event.metadata)


def test_weak_passwords_are_refused_and_asked_again(monkeypatch):
    passwords = iter(["password123", "Short-1a", STRONG, STRONG])
    _out, err = run(monkeypatch, iter(["boss@example.edu"]), passwords)
    assert User.objects.get().check_password(STRONG)
    assert err.count("\n") >= 2


def test_mismatched_confirmation_asks_again(monkeypatch):
    passwords = iter([STRONG, "Another-Strong-Pass-7", STRONG, STRONG])
    _out, err = run(monkeypatch, iter(["boss@example.edu"]), passwords)
    assert "do not match" in err and User.objects.count() == 1


def test_gives_up_after_repeated_bad_input(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "not-an-email")
    with pytest.raises(CommandError, match="Too many"):
        call_command("create_admin", stdout=StringIO(), stderr=StringIO())
    assert not User.objects.exists()


def test_refuses_an_email_that_is_already_taken(monkeypatch):
    User.objects.create_user(Role.TEACHER, contact_email="boss@example.edu")
    with pytest.raises(CommandError, match="already in use"):
        run(monkeypatch, iter(["Boss@Example.edu"]), iter([STRONG, STRONG]))
    assert User.objects.filter(role=Role.ADMIN).count() == 0


@pytest.mark.parametrize(
    "password",
    ["password123", "Short-1a", "alllowercaselongpassword", "12345678901234567890", "a" * 30],
)
def test_strong_password_rule_rejects(password):
    with pytest.raises(ValidationError):
        validate_strong_password(password)


def test_strong_password_rule_accepts():
    validate_strong_password(STRONG)
    validate_strong_password("a-long passphrase with spaces and 2 numbers")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("=SUM(A1)", "'=SUM(A1)"),
        ("+1", "'+1"),
        ("-1", "'-1"),
        ("@cmd", "'@cmd"),
        ("\tx", "'\tx"),
        ("2101001", "2101001"),
        (None, ""),
        (7, "7"),
    ],
)
def test_csv_cells_cannot_start_a_formula(value, expected):
    assert safe_cell(value) == expected
