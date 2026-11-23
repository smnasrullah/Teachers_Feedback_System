import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.accounts.models import User
from apps.core.permissions import Role

pytestmark = pytest.mark.django_db


@override_settings(
    DJANGO_SECRET_KEY="test-secret",
    FIELD_ENCRYPTION_KEYS=["n8Mc0WusTz3W2F5mK7qE1vR9xC4dH6pA2sL0gJ8uB5Y="],
)
def test_bootstrap_admin_creates_real_admin(monkeypatch):
    monkeypatch.setenv("REAL_ADMIN_USERNAME", "adm_real01")
    monkeypatch.setenv("REAL_ADMIN_EMAIL", "real@example.edu")
    monkeypatch.setenv("REAL_ADMIN_PASSWORD", "Correct-Horse-Battery-9")

    call_command("bootstrap_admin")

    user = User.objects.get(username="adm_real01")
    assert user.role == Role.ADMIN
    assert user.check_password("Correct-Horse-Battery-9")
    assert user.contact_email == "real@example.edu"


def test_bootstrap_admin_updates_password(monkeypatch):
    user = User.objects.create_admin(
        "Old-Password-123!",
        username="adm_real01",
        contact_email="real@example.edu",
    )
    monkeypatch.setenv("REAL_ADMIN_USERNAME", "adm_real01")
    monkeypatch.setenv("REAL_ADMIN_EMAIL", "real@example.edu")
    monkeypatch.setenv("REAL_ADMIN_PASSWORD", "Correct-Horse-Battery-9")

    call_command("bootstrap_admin")

    user.refresh_from_db()
    assert user.check_password("Correct-Horse-Battery-9")


def test_bootstrap_admin_rejects_missing_environment(monkeypatch):
    monkeypatch.delenv("REAL_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("REAL_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("REAL_ADMIN_PASSWORD", raising=False)

    with pytest.raises(CommandError, match="REAL_ADMIN_PASSWORD"):
        call_command("bootstrap_admin")
