"""Password-only sign-in for the local demo accounts, and every way it must stay off."""

import pytest
from django.core.management import call_command
from django.core.management.base import SystemCheckError
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.services import login as login_service
from apps.auditlog.models import AuditEvent
from apps.core.checks import check_demo_second_factor
from apps.core.permissions import Role
from apps.core.services.demo import constants as demo
from tests.auth_helpers import enable_totp
from tests.factories import claim, make_admin, make_student, make_user
from tests.test_demo_seed import PASSWORD, seed

LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}


@pytest.fixture
def seeded(db, settings):
    seed(settings, "--password", PASSWORD)


@pytest.fixture
def dev(settings):
    settings.DEMO_SKIP_SECOND_FACTOR = True
    settings.DEBUG = True
    settings.SETTINGS_MODULE = "config.settings.dev"  # set last: each override resets it


def sign_in(username, password=PASSWORD, **extra):
    client = Client(HTTP_ACCEPT_LANGUAGE="en", **extra)
    response = client.post(reverse("accounts:login"), {"username": username, "password": password})
    return client, response


def asks_for_code(response) -> bool:
    return response.status_code == 302 and response["Location"] in (
        reverse("accounts:login_second_factor"),
        reverse("accounts:login_two_factor_setup"),
    )


@pytest.mark.parametrize("username", demo.USERNAMES)
def test_demo_accounts_sign_in_with_a_password_only(seeded, dev, username):
    client, response = sign_in(username, **LOOPBACK)
    assert response.status_code == 302
    assert not asks_for_code(response)
    assert client.get(response["Location"]).status_code == 200
    assert client.get(reverse("accounts:account")).status_code == 200
    user = User.objects.get(username=username)
    event = AuditEvent.objects.get(action="auth.login_demo_bypass", actor_id=user.pk)
    assert PASSWORD not in str(event.metadata)


def test_ipv6_loopback_counts_too(seeded, dev):
    _client, response = sign_in(demo.STUDENT, REMOTE_ADDR="::1")
    assert not asks_for_code(response)


@pytest.mark.parametrize(
    "case",
    ["debug_off", "other_settings", "lan_address", "forwarded", "flag_off"],
)
def test_demo_accounts_are_asked_for_the_code_outside_a_local_dev_server(
    seeded, dev, settings, case
):
    extra = dict(LOOPBACK)
    if case == "debug_off":
        settings.DEBUG = False
    elif case == "other_settings":
        settings.SETTINGS_MODULE = "config.settings.test"
    elif case == "flag_off":
        settings.DEMO_SKIP_SECOND_FACTOR = False
    elif case == "lan_address":
        extra = {"REMOTE_ADDR": "192.168.1.20"}
    else:
        extra["HTTP_X_FORWARDED_FOR"] = "203.0.113.9"
    for username in demo.USERNAMES:
        _client, response = sign_in(username, **extra)
        assert asks_for_code(response), (case, username)
    assert not AuditEvent.objects.filter(action="auth.login_demo_bypass").exists()


def test_a_demo_name_alone_is_not_enough(db, dev):
    stranger = make_user("demo_stranger", Role.STUDENT, PASSWORD)
    enable_totp(stranger)
    real_row = claim(make_student(), PASSWORD, username="demo_real")
    enable_totp(real_row)
    plain_admin = make_admin(PASSWORD, username="demo_plain")
    enable_totp(plain_admin)
    for username in ("demo_stranger", "demo_real", "demo_plain"):
        _client, response = sign_in(username, **LOOPBACK)
        assert asks_for_code(response), username


def test_real_users_always_get_the_code_prompt(db, dev):
    user = claim(make_student(), PASSWORD)
    enable_totp(user)
    admin = make_admin(PASSWORD)
    enable_totp(admin)
    for account in (user, admin):
        _client, response = sign_in(account.username, **LOOPBACK)
        assert asks_for_code(response)


def test_the_password_is_still_required(seeded, dev):
    client, response = sign_in(demo.ADMIN, "Wrong-Pass-1!", **LOOPBACK)
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session
    assert not AuditEvent.objects.filter(action="auth.login_demo_bypass").exists()


def test_lockout_still_applies(seeded, dev, settings):
    for _attempt in range(settings.AXES_FAILURE_LIMIT):
        sign_in(demo.STUDENT, "Wrong-Pass-1!", **LOOPBACK)
    client, response = sign_in(demo.STUDENT, **LOOPBACK)
    assert response.status_code == 429
    assert "_auth_user_id" not in client.session


def test_the_check_refuses_the_flag_outside_development(settings):
    settings.DEMO_SKIP_SECOND_FACTOR = True
    for debug, module in (
        (False, "config.settings.dev"),
        (True, "config.settings.prod"),
        (False, "config.settings.prod"),
    ):
        settings.DEBUG = debug
        settings.SETTINGS_MODULE = module
        assert [error.id for error in check_demo_second_factor(None)] == ["core.E004"]
    settings.DEBUG = True
    settings.SETTINGS_MODULE = "config.settings.dev"
    assert check_demo_second_factor(None) == []
    settings.DEMO_SKIP_SECOND_FACTOR = False
    settings.DEBUG = False
    assert check_demo_second_factor(None) == []


def test_the_check_runs_with_the_system_checks(settings):
    settings.DEMO_SKIP_SECOND_FACTOR = True
    with pytest.raises(SystemCheckError, match=r"core.E004"):
        call_command("check")


def test_the_helper_is_closed_by_default(rf, db):
    request = rf.get("/", **LOOPBACK)
    assert not login_service.is_demo_account(request, make_user("demo_x", Role.STUDENT))
