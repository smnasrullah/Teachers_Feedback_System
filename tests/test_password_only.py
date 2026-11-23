"""Password-only sign-in, the default (``TOTP_REQUIRED_ROLES`` empty), and the per-role switch.

The authenticator path itself, with every role required to use it, is covered by
test_login.py, test_signup.py and test_twofactor.py.
"""

import pytest
from django.conf import settings as django_settings
from django.test import Client, override_settings
from django.urls import reverse

from apps.accounts.models import IdRegistry, RecoveryCode, User
from apps.core.checks import PROD_SETTINGS, check_second_factor_roles
from apps.core.models import ActiveSession
from tests.auth_helpers import claimable_student, claimable_teacher
from tests.factories import claim, make_admin, make_hod, make_student, make_teacher, sign_in

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ng-Passw0rd!x"
CODE_FIELD_MARKERS = ('autocomplete="one-time-code"', "otp-input", "recovery code")
GENERIC_LOGIN = "Invalid ID or password."


def url(name, *args):
    return reverse(f"accounts:{name}", args=args)


def has_code_field(html: str) -> bool:
    lowered = html.lower()
    return any(marker.lower() in lowered for marker in CODE_FIELD_MARKERS)


def sign_up(web, profile, code, password=PASSWORD):
    claimed = web.post(
        url("signup"), {"registry_id": profile.registry.external_id, "activation_code": code}
    )
    assert claimed.context["stage"] == "password"
    return web.post(url("signup_password"), {"password1": password, "password2": password})


def account_of(profile) -> User | None:
    return IdRegistry.objects.get(pk=profile.registry_id).claimed_by


def accounts_by_role() -> dict[str, User]:
    student = claim(make_student(), PASSWORD)
    teacher = claim(make_teacher(), PASSWORD)
    hod = make_hod()
    hod.set_password(PASSWORD)
    hod.save()
    return {
        "student": student,
        "teacher": teacher,
        "hod": hod,
        "admin": make_admin(PASSWORD),
    }


def log_in(web, user, password=PASSWORD):
    return web.post(url("login"), {"username": user.username, "password": password})


# --- default: nobody needs an authenticator ----------------------------------------------------


def test_no_role_needs_an_authenticator_by_default():
    assert not django_settings.TOTP_REQUIRED_ROLES


def test_signup_finishes_after_the_password_and_signs_the_person_in(web):
    profile, code = claimable_student()
    response = sign_up(web, profile, code)
    user = account_of(profile)
    assert response.context["stage"] == "done"
    assert response.context["codes"] == []
    assert [label for _number, label in response.context["steps"]][-1] == "Account ready"
    html = response.content.decode()
    assert user.username in html
    assert not has_code_field(html)
    assert "data:image/svg+xml" not in html  # no QR code
    assert user.check_password(PASSWORD)
    assert not user.totp_enabled and user.totp_secret is None
    assert not RecoveryCode.objects.filter(user=user).exists()
    assert "signup" not in web.session
    assert web.get(url("dashboard_student")).status_code == 200


def test_every_signup_step_is_free_of_code_fields(web):
    profile, code = claimable_teacher()
    pages = [web.get(url("signup"))]
    pages.append(
        web.post(
            url("signup"), {"registry_id": profile.registry.external_id, "activation_code": code}
        )
    )
    for page in pages:
        assert not has_code_field(page.content.decode())
        assert "Authenticator" not in page.content.decode()


@pytest.mark.parametrize("role", ["student", "teacher", "hod", "admin"])
def test_every_role_logs_in_with_username_and_password_only(role):
    user = accounts_by_role()[role]
    web = Client(HTTP_ACCEPT_LANGUAGE="en")
    response = log_in(web, user)
    assert response.status_code == 302
    assert response["Location"] not in {url("login_second_factor"), url("login_two_factor_setup")}
    assert web.get(response["Location"]).status_code == 200
    assert ActiveSession.objects.filter(user=user).exists()


@pytest.mark.parametrize("role", ["student", "teacher", "hod", "admin"])
def test_no_page_shows_a_code_field_or_recovery_codes(role):
    user = accounts_by_role()[role]
    web = Client(HTTP_ACCEPT_LANGUAGE="en")
    for name in ("login", "signup", "password_forgot", "username_forgot"):
        assert not has_code_field(web.get(url(name)).content.decode()), name
    sign_in(web, user)
    for name in ("account", "password_change", "step_up"):
        html = web.get(url(name)).content.decode()
        assert not has_code_field(html), name
        assert url("two_factor") not in html


@pytest.mark.parametrize(
    "name",
    [
        "login_second_factor",
        "login_two_factor_setup",
        "signup_authenticator",
        "password_forgot_new",
    ],
)
def test_old_code_urls_redirect_a_visitor_safely(web, name):
    response = web.get(url(name))
    assert response.status_code == 302
    assert response["Location"].startswith("/")


@pytest.mark.parametrize(
    ("method", "name"),
    [
        ("get", "two_factor"),
        ("get", "two_factor_device_confirm"),
        ("post", "two_factor_regenerate"),
        ("post", "two_factor_device"),
    ],
)
def test_authenticator_management_sends_a_signed_in_person_back(web, method, name):
    sign_in(web, claim(make_student(), PASSWORD))
    response = getattr(web, method)(url(name))
    assert response.status_code == 302
    assert response["Location"] == url("account")


def test_a_stored_authenticator_is_ignored_while_the_role_is_not_required(web):
    user = claim(make_student(), PASSWORD)
    User.objects.filter(pk=user.pk).update(totp_secret="JBSWY3DPEHPK3PXP", totp_enabled=True)
    response = log_in(web, user)
    assert response["Location"] == url("dashboard_student")
    assert User.objects.get(pk=user.pk).totp_secret == "JBSWY3DPEHPK3PXP"  # kept, unused


# --- the switch: admin and hod only -------------------------------------------------------------


@override_settings(TOTP_REQUIRED_ROLES=frozenset({"admin", "hod"}))
@pytest.mark.parametrize(
    ("role", "needs_code"),
    [("student", False), ("teacher", False), ("hod", True), ("admin", True)],
)
def test_login_asks_for_a_code_only_for_the_required_roles(role, needs_code):
    user = accounts_by_role()[role]
    web = Client(HTTP_ACCEPT_LANGUAGE="en")
    response = log_in(web, user)
    second_step = {url("login_second_factor"), url("login_two_factor_setup")}
    assert (response["Location"] in second_step) is needs_code
    # The password alone signs in only the roles that need no code.
    assert ActiveSession.objects.filter(user=user).exists() is not needs_code


@override_settings(TOTP_REQUIRED_ROLES=frozenset({"admin", "hod"}))
def test_a_head_of_department_enrols_an_authenticator_at_signup(web):
    profile, code = claimable_teacher()
    profile.is_hod = True
    profile.hod_department = profile.registry.department
    profile.save()
    response = sign_up(web, profile, code)
    assert response.context["stage"] == "authenticator"
    assert "data:image/svg+xml" in response.content.decode()
    assert account_of(profile) is None


@override_settings(TOTP_REQUIRED_ROLES=frozenset({"admin", "hod"}))
@pytest.mark.parametrize("make", [claimable_student, claimable_teacher])
def test_students_and_teachers_still_sign_up_with_a_password_only(web, make):
    profile, code = make()
    response = sign_up(web, profile, code)
    assert response.context["stage"] == "done"
    assert not account_of(profile).totp_enabled


@override_settings(TOTP_REQUIRED_ROLES=frozenset({"admin"}))
def test_a_session_without_the_code_ends_once_the_role_becomes_required(web):
    admin = make_admin(PASSWORD)
    with override_settings(TOTP_REQUIRED_ROLES=frozenset()):
        log_in(web, admin)
    response = web.get(url("dashboard_admin"))
    assert response.status_code == 302
    assert response["Location"].startswith(url("login"))


# --- compensating controls ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "password",
    ["Sh0rt!pass1", "password1234", "123456789012345", "<username>"],
    ids=["too_short", "common", "numeric", "like_the_username"],
)
def test_signup_rejects_weak_passwords(web, password):
    profile, code = claimable_student()
    web.post(url("signup"), {"registry_id": profile.registry.external_id, "activation_code": code})
    username = web.session["signup"]["username"]
    password = password.replace("<username>", f"{username}x")
    response = web.post(url("signup_password"), {"password1": password, "password2": password})
    assert response.context["stage"] == "password"
    assert response.context["form"].errors["password1"]
    assert account_of(profile) is None


def test_the_minimum_length_is_twelve():
    validators = {
        item["NAME"].rsplit(".", 1)[-1]: item for item in django_settings.AUTH_PASSWORD_VALIDATORS
    }
    assert validators["MinimumLengthValidator"]["OPTIONS"]["min_length"] == 12
    assert {
        "UserAttributeSimilarityValidator",
        "CommonPasswordValidator",
        "NumericPasswordValidator",
    } <= set(validators)


def test_password_change_rejects_a_weak_password(web):
    user = claim(make_student(), PASSWORD)
    sign_in(web, user)
    response = web.post(
        url("password_change"),
        {"current_password": PASSWORD, "password1": "short-1A", "password2": "short-1A"},
    )
    assert response.status_code == 200
    assert response.context["form"].errors["password1"]
    assert User.objects.get(pk=user.pk).check_password(PASSWORD)


def test_unknown_user_and_wrong_password_get_the_same_answer(web):
    user = claim(make_student(), PASSWORD)
    known = log_in(web, user, "Wrong-Passw0rd!x")
    unknown = web.post(url("login"), {"username": "stu_nobody1", "password": "Wrong-Passw0rd!x"})
    assert known.status_code == unknown.status_code == 200
    assert GENERIC_LOGIN in known.content.decode()
    assert GENERIC_LOGIN in unknown.content.decode()
    assert known.context["form"].errors == unknown.context["form"].errors


def test_repeated_wrong_passwords_lock_the_login(web):
    user = claim(make_student(), PASSWORD)
    for _ in range(django_settings.AXES_FAILURE_LIMIT):
        log_in(web, user, "Wrong-Passw0rd!x")
    locked = log_in(web, user)
    assert locked.status_code == 429
    assert not ActiveSession.objects.filter(user=user).exists()


def test_the_login_form_is_rate_limited(web):
    statuses = [
        web.post(url("login"), {"username": "stu_flood01", "password": f"guess-{n}"}).status_code
        for n in range(12)
    ]
    assert 429 in statuses


@pytest.mark.parametrize(
    "name", ["login", "signup", "password_forgot", "password_forgot_new", "username_forgot"]
)
def test_auth_pages_are_never_cached(web, name):
    response = web.get(url(name))
    assert "no-store" in response["Cache-Control"]


def test_signed_in_auth_pages_are_never_cached(web):
    sign_in(web, claim(make_student(), PASSWORD))
    for name in ("step_up", "account", "password_change"):
        assert "no-store" in web.get(url(name))["Cache-Control"], name


def test_session_cookie_flags_are_unchanged():
    assert django_settings.SESSION_COOKIE_HTTPONLY
    assert django_settings.SESSION_COOKIE_SAMESITE == "Lax"
    assert django_settings.SESSION_EXPIRE_AT_BROWSER_CLOSE


# --- production visibility ---------------------------------------------------------------------


def test_prod_warns_when_no_role_needs_a_second_factor(settings):
    settings.TOTP_REQUIRED_ROLES = frozenset()
    settings.SETTINGS_MODULE = PROD_SETTINGS  # set last: each override resets it
    issues = check_second_factor_roles(None)
    assert [issue.id for issue in issues] == ["core.W001"]
    assert issues[0].msg == (
        "No second factor is required for any role. Consider requiring it for admin and hod."
    )


def test_prod_is_quiet_when_a_role_needs_a_second_factor(settings):
    settings.TOTP_REQUIRED_ROLES = frozenset({"admin", "hod"})
    settings.SETTINGS_MODULE = PROD_SETTINGS
    assert check_second_factor_roles(None) == []


def test_development_does_not_warn(settings):
    settings.TOTP_REQUIRED_ROLES = frozenset()
    assert check_second_factor_roles(None) == []


def test_an_unknown_role_name_is_an_error(settings):
    settings.TOTP_REQUIRED_ROLES = frozenset({"admin", "dean"})
    assert [issue.id for issue in check_second_factor_roles(None)] == ["core.E005"]
