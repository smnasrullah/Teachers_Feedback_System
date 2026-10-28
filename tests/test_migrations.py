from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from django.test import Client
from django.urls import reverse
from django.utils import translation

from apps.accounts.models import User
from apps.core.services.migrations import unapplied_migrations

pytestmark = pytest.mark.django_db

STRONG = "Correct-Horse-Battery-9"


@pytest.fixture(autouse=True)
def english():
    with translation.override("en"):
        yield


def create_admin(monkeypatch, email="boss@example.edu"):
    passwords = iter([STRONG, STRONG])
    monkeypatch.setattr("builtins.input", lambda _prompt: email)
    monkeypatch.setattr(
        "apps.accounts.management.commands.create_admin.getpass", lambda _prompt: next(passwords)
    )
    call_command("create_admin", stdout=StringIO(), stderr=StringIO())


def test_models_and_migrations_agree():
    """Fails when a model change ships without its migration."""
    out = StringIO()
    try:
        call_command("makemigrations", "--check", "--dry-run", stdout=out)
    except SystemExit:
        pytest.fail(f"Missing migrations:\n{out.getvalue()}")


def test_fresh_database_migrate_create_admin_then_log_in(monkeypatch):
    call_command("migrate", verbosity=0)
    assert unapplied_migrations() == []
    create_admin(monkeypatch)
    admin = User.objects.get()
    web = Client(HTTP_ACCEPT_LANGUAGE="en")
    response = web.post(reverse("accounts:login"), {"username": admin.username, "password": STRONG})
    assert response.status_code == 302
    assert response["Location"] == reverse("accounts:login_two_factor_setup")


def test_create_admin_refuses_while_migrations_are_unapplied(monkeypatch):
    MigrationRecorder(connection).record_unapplied("accounts", "0004_remove_one_time_codes")
    assert ("accounts", "0004_remove_one_time_codes") in unapplied_migrations()
    with pytest.raises(CommandError, match=r"Run: python manage\.py migrate"):
        create_admin(monkeypatch)
    assert not User.objects.exists()
