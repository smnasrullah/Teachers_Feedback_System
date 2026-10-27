import re
import time

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.services.recovery import RESET_KEY
from apps.auditlog.models import AuditEvent
from apps.core.models import ActiveSession
from tests.auth_helpers import enable_totp, fresh_code, totp_code
from tests.factories import PASSWORD, claim, make_admin, make_student

pytestmark = pytest.mark.django_db

NEW_PASSWORD = "Brand-New-Passw0rd"
GENERIC = "The username or code is not correct."


def url(name):
    return reverse(f"accounts:{name}")


def account():
    user = claim(make_student(), PASSWORD)
    codes = enable_totp(user)
    return user, codes


def fresh_client():
    return Client(HTTP_ACCEPT_LANGUAGE="en")


def strip_tokens(response):
    """The page without its per-request tokens (CSRF and CSP nonce)."""
    return re.sub(r'(value|content|nonce)="[A-Za-z0-9_-]{16,}"', r'=""', response.content.decode())


def request_reset(web, username, code, **extra):
    return web.post(url("password_forgot"), {"username": username, "code": code}, **extra)


def set_new_password(web, password=NEW_PASSWORD):
    return web.post(url("password_forgot_new"), {"password1": password, "password2": password})


def test_password_reset_with_the_authenticator_end_to_end(web):
    user, _codes = account()
    web.post(url("login"), {"username": user.username, "password": PASSWORD})
    web.post(url("login_second_factor"), {"code": fresh_code(user)})
    assert ActiveSession.objects.filter(user=user).exists()
    web.post(url("logout"))
    for _attempt in range(4):  # almost locked out: a reset must also clear the count
        web.post(url("login"), {"username": user.username, "password": "Wrong-password-1"})

    assert request_reset(web, user.username, fresh_code(user))["Location"] == url(
        "password_forgot_new"
    )
    assert set_new_password(web)["Location"] == url("login")

    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)
    assert not ActiveSession.objects.filter(user=user).exists()
    assert RESET_KEY not in web.session
    assert AuditEvent.objects.filter(action="auth.password_reset", actor_id=user.pk).exists()
    for _attempt in range(4):
        web.post(url("login"), {"username": user.username, "password": "Wrong-password-1"})
    login = web.post(url("login"), {"username": user.username, "password": NEW_PASSWORD})
    assert login["Location"] == url("login_second_factor")  # not locked out


def test_a_recovery_code_works_once_for_a_reset(web):
    user, codes = account()
    assert request_reset(web, user.username, codes[0].lower())["Location"] == url(
        "password_forgot_new"
    )
    assert AuditEvent.objects.get(action="auth.recovery_code_used").metadata == {"remaining": 7}
    web.session.flush()
    again = request_reset(web, user.username, codes[0])
    assert again.status_code == 200
    assert again.context["form"].non_field_errors() == [GENERIC]


def test_the_code_used_for_a_reset_cannot_be_replayed(web):
    user, _codes = account()
    code = totp_code(user, steps_ahead=1)
    request_reset(web, user.username, code)
    web.session.flush()
    replay = request_reset(web, user.username, code)
    assert replay.context["form"].non_field_errors() == [GENERIC]


@pytest.mark.parametrize("kind", ["unknown", "inactive", "no_authenticator", "wrong_code"])
def test_every_failure_gets_the_same_answer(kind):
    user, _codes = account()
    code = fresh_code(user)
    username = user.username
    if kind == "unknown":
        username = "stu_nobody1"
    elif kind == "inactive":
        User.objects.filter(pk=user.pk).update(is_active=False)
    elif kind == "no_authenticator":
        username = claim(make_student(), PASSWORD).username
    else:
        code = "000000" if code != "000000" else "111111"
    wrong_web, failing_web = fresh_client(), fresh_client()
    reference = request_reset(wrong_web, "stu_ghost99", "123456")
    response = request_reset(failing_web, username, code)
    assert response.status_code == reference.status_code == 200
    assert response.context["form"].non_field_errors() == [GENERIC]
    assert RESET_KEY not in failing_web.session
    assert strip_tokens(response).replace(username, "") == strip_tokens(reference).replace(
        "stu_ghost99", ""
    )


@pytest.mark.parametrize("known", [True, False])
def test_repeated_wrong_codes_lock_out_known_and_unknown_usernames_alike(web, known):
    user, _codes = account()
    username = user.username if known else "stu_ghost99"
    responses = [
        request_reset(web, username, "000000", REMOTE_ADDR="198.51.100.40") for _ in range(5)
    ]
    assert responses[-1].status_code == 429
    assert "Too many failed attempts" in responses[-1].content.decode()
    refused = request_reset(web, user.username if known else username, fresh_code(user))
    assert refused.status_code == 429
    assert RESET_KEY not in web.session
    assert AuditEvent.objects.filter(
        action="auth.login_failed", metadata__stage="password_reset"
    ).exists()


def test_new_password_page_needs_a_verified_code(web):
    assert web.get(url("password_forgot_new"))["Location"] == url("password_forgot")
    user, _codes = account()
    request_reset(web, user.username, "000000")
    assert web.get(url("password_forgot_new"))["Location"] == url("password_forgot")


def test_a_verified_reset_expires(web, settings):
    user, _codes = account()
    request_reset(web, user.username, fresh_code(user))
    session = web.session
    session[RESET_KEY]["at"] = int(time.time()) - settings.SECOND_FACTOR_PENDING_SECONDS - 5
    session.save()
    assert web.get(url("password_forgot_new"))["Location"] == url("password_forgot")


def test_reset_enforces_the_password_rules(web):
    admin = make_admin(PASSWORD)
    enable_totp(admin)
    request_reset(web, admin.username, fresh_code(admin))
    weak = "Abcdefg1234"
    response = set_new_password(web, weak)
    assert "password1" in response.context["form"].errors
    admin.refresh_from_db()
    assert admin.check_password(PASSWORD)


def test_reset_does_not_bypass_the_second_factor(web):
    user, _codes = account()
    request_reset(web, user.username, fresh_code(user))
    set_new_password(web)
    response = web.post(url("login"), {"username": user.username, "password": NEW_PASSWORD})
    assert response["Location"] == url("login_second_factor")
    assert "_auth_user_id" not in web.session


def test_nothing_secret_reaches_the_audit_log(web):
    user, codes = account()
    request_reset(web, user.username, codes[1])
    set_new_password(web)
    for event in AuditEvent.objects.all():
        text = str(event.metadata)
        assert codes[1] not in text
        assert NEW_PASSWORD not in text
        assert user.totp_secret not in text


def test_forgot_password_is_rate_limited_per_username_and_per_ip(web):
    per_username = [
        request_reset(web, "stu_target1", "123456", REMOTE_ADDR=f"198.51.100.{n}").status_code
        for n in range(1, 8)
    ]
    assert per_username[:5] == [200] * 5
    assert per_username[5:] == [429, 429]
    per_ip = [
        request_reset(web, f"stu_n{n:04d}", "123456", REMOTE_ADDR="203.0.113.5").status_code
        for n in range(12)
    ]
    assert per_ip[:10] == [200] * 10
    assert per_ip[10:] == [429, 429]


def test_forgot_username_sends_people_to_their_department(web):
    page = web.get(url("username_forgot"))
    assert page.status_code == 200
    assert "Ask your department office or the Admin" in page.content.decode()
    assert web.post(url("username_forgot"), {"registry_id": "2100001"}).status_code == 405
