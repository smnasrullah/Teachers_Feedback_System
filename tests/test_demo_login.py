"""Password-only sign-in for the local demo accounts, and every way it must stay off."""

import pytest
from django.core.management import call_command
from django.core.management.base import SystemCheckError
from django.test import Client
from django.urls import reverse

from apps.accounts import ratelimits
from apps.accounts.models import User
from apps.accounts.services import login as login_service
from apps.auditlog.models import AuditEvent
from apps.core.checks import check_demo_second_factor
from apps.core.permissions import Role
from apps.core.services.demo import constants as demo
from tests.auth_helpers import enable_totp
from tests.factories import claim, make_admin, make_student, make_teacher, make_user
from tests.factories import sign_in as force_sign_in
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
    teacher = claim(make_teacher(), PASSWORD)
    enable_totp(teacher)
    for account in (user, admin, teacher):
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


def test_the_check_allows_password_only_login_only_for_the_isolated_demo_module(settings):
    settings.DEBUG = False
    settings.IS_DEMO_SITE = True
    settings.DEMO_DATABASE_ISOLATED = True
    settings.DEMO_SKIP_SECOND_FACTOR = True
    settings.SETTINGS_MODULE = "config.settings.demo"
    assert check_demo_second_factor(None) == []
    settings.SETTINGS_MODULE = "config.settings.prod"
    assert [error.id for error in check_demo_second_factor(None)] == ["core.E004"]
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


def test_the_demo_teacher_signs_in_with_the_password_only_from_loopback(seeded, dev):
    _client, response = sign_in(demo.TEACHER, **LOOPBACK)
    assert not asks_for_code(response)
    _client, response = sign_in(demo.TEACHER, REMOTE_ADDR="192.168.1.20")
    assert asks_for_code(response)


def test_public_demo_accounts_skip_second_factor_only_on_isolated_demo_site(seeded, settings):
    settings.DEBUG = False
    settings.SETTINGS_MODULE = "config.settings.demo"
    settings.IS_DEMO_SITE = True
    settings.DEMO_DATABASE_ISOLATED = True
    settings.SITE_URL = "https://teachers-feedback-demo.onrender.com"
    settings.DEMO_SKIP_SECOND_FACTOR = True
    settings.SETTINGS_MODULE = "config.settings.demo"

    for username in demo.USERNAMES:
        client, response = sign_in(
            username,
            REMOTE_ADDR="203.0.113.20",
            HTTP_X_FORWARDED_FOR="198.51.100.30",
        )
        assert response.status_code == 302
        assert not asks_for_code(response)
        assert client.get(response["Location"]).status_code == 200
    assert AuditEvent.objects.filter(action="auth.login_demo_bypass").count() == len(demo.USERNAMES)


def test_the_login_box_shows_the_password_only_in_development(seeded, dev, settings):
    settings.DEMO_PASSWORD = PASSWORD
    settings.SETTINGS_MODULE = "config.settings.dev"  # set last: each override resets it
    url = reverse("accounts:login")
    html = Client(HTTP_ACCEPT_LANGUAGE="en").get(url).content.decode()
    assert html.count(PASSWORD) == len(demo.USERNAMES) + 1  # per "Fill in" button, and once shown
    assert "<details" not in html
    assert 'data-demo-login' in html
    for label in ("Administrator", "Head of department", "Teacher", "Student"):
        assert label in html
    settings.DEBUG = False
    for module in ("config.settings.dev", "config.settings.prod"):
        settings.SETTINGS_MODULE = module
        html = Client(HTTP_ACCEPT_LANGUAGE="en").get(url).content.decode()
        assert PASSWORD not in html
        assert "Demo accounts" not in html
    settings.DEBUG = True
    settings.SETTINGS_MODULE = "config.settings.test"
    html = Client(HTTP_ACCEPT_LANGUAGE="en").get(url).content.decode()
    assert PASSWORD not in html


def test_public_demo_login_box_shows_credentials_only_when_all_accounts_match(seeded, settings):
    settings.DEBUG = False
    settings.SETTINGS_MODULE = "config.settings.demo"
    settings.IS_DEMO_SITE = True
    settings.DEMO_DATABASE_ISOLATED = True
    settings.SITE_URL = "https://teachers-feedback-demo.onrender.com"
    settings.DEMO_PASSWORD = PASSWORD
    settings.SETTINGS_MODULE = "config.settings.demo"
    url = reverse("accounts:login")

    html = Client(HTTP_ACCEPT_LANGUAGE="en").get(url).content.decode()
    assert html.count(PASSWORD) == len(demo.USERNAMES) + 1
    assert all(username in html for username in demo.USERNAMES)

    settings.DEMO_PASSWORD = "Stale-Demo-Password-2026!"
    html = Client(HTTP_ACCEPT_LANGUAGE="en").get(url).content.decode()
    assert "Demo accounts" not in html
    assert "Stale-Demo-Password-2026!" not in html


def test_public_demo_accounts_work_on_the_production_site(seeded, settings):
    settings.DEBUG = False
    settings.IS_DEMO_SITE = True
    settings.DEMO_DATABASE_ISOLATED = False
    settings.PUBLIC_DEMO_ENABLED = True
    settings.DEMO_SKIP_SECOND_FACTOR = True
    settings.DEMO_PASSWORD = PASSWORD
    settings.SETTINGS_MODULE = "config.settings.prod"  # set last: overrides reset this marker

    assert (
        settings.DEBUG,
        settings.IS_DEMO_SITE,
        settings.SETTINGS_MODULE,
        settings.PUBLIC_DEMO_ENABLED,
        settings.DEMO_DATABASE_ISOLATED,
    ) == (False, True, "config.settings.prod", True, False)
    users = User.objects.filter(username__in=demo.USERNAMES, is_active=True)
    assert users.count() == len(demo.USERNAMES)
    assert all(user.check_password(PASSWORD) for user in users)
    assert login_service.demo_box() == {
        "accounts": login_service.DEMO_ROLES,
        "password": PASSWORD,
    }
    html = Client(HTTP_ACCEPT_LANGUAGE="en").get(reverse("accounts:login")).content.decode()
    assert all(username in html for username in demo.USERNAMES)
    assert html.count(PASSWORD) == len(demo.USERNAMES) + 1

    for username in demo.USERNAMES:
        client, response = sign_in(username, PASSWORD, REMOTE_ADDR="203.0.113.10")
        assert response.status_code == 302
        assert not asks_for_code(response)
        assert "_auth_user_id" in client.session


def test_public_demo_bypass_does_not_apply_to_real_accounts(seeded, settings):
    settings.DEBUG = False
    settings.IS_DEMO_SITE = True
    settings.PUBLIC_DEMO_ENABLED = True
    settings.DEMO_SKIP_SECOND_FACTOR = True
    settings.DEMO_PASSWORD = PASSWORD
    settings.SETTINGS_MODULE = "config.settings.prod"  # set last: overrides reset this marker
    real = make_user("stu_real", Role.STUDENT, PASSWORD)
    enable_totp(real)

    _client, response = sign_in(real.username, PASSWORD, REMOTE_ADDR="203.0.113.10")
    assert asks_for_code(response)


def test_public_demo_rate_limit_subject_is_separated_by_visitor_ip(settings, rf):
    settings.PUBLIC_DEMO_ENABLED = True
    first = rf.post("/login/", {"username": demo.STUDENT}, REMOTE_ADDR="198.51.100.10")
    second = rf.post("/login/", {"username": demo.STUDENT}, REMOTE_ADDR="198.51.100.20")
    assert ratelimits.username(None, first) != ratelimits.username(None, second)

    first_real = rf.post("/login/", {"username": "stu_someone"}, REMOTE_ADDR="198.51.100.10")
    second_real = rf.post("/login/", {"username": "stu_someone"}, REMOTE_ADDR="198.51.100.20")
    assert ratelimits.username(None, first_real) == ratelimits.username(None, second_real)


def test_shared_demo_account_cannot_change_the_public_password(seeded, settings):
    settings.DEBUG = False
    settings.IS_DEMO_SITE = True
    settings.DEMO_DATABASE_ISOLATED = True
    settings.SETTINGS_MODULE = "config.settings.demo"
    user = User.objects.get(username=demo.STUDENT)
    client = Client(HTTP_ACCEPT_LANGUAGE="en")
    force_sign_in(client, user)

    response = client.post(
        reverse("accounts:password_change"),
        {
            "current_password": PASSWORD,
            "password1": "New-Demo-Pass-2026!",
            "password2": "New-Demo-Pass-2026!",
        },
    )

    user.refresh_from_db()
    assert response.status_code == 302
    assert user.check_password(PASSWORD)


def test_a_stale_password_is_never_shown(seeded, dev, settings):
    settings.DEMO_PASSWORD = "Not-The-Demo-Pass-1!"
    settings.SETTINGS_MODULE = "config.settings.dev"  # set last: each override resets it
    html = Client(HTTP_ACCEPT_LANGUAGE="en").get(reverse("accounts:login")).content.decode()
    assert "Not-The-Demo-Pass-1!" not in html
    assert "data-fill-username" in html
