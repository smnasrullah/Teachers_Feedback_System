import re
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import OneTimeCode, User
from apps.auditlog.models import AuditEvent
from apps.core.models import ActiveSession
from tests.auth_helpers import enable_totp
from tests.factories import PASSWORD, claim, make_admin, make_student

pytestmark = pytest.mark.django_db

EMAIL = "stu.recover@example.com"
NEW_PASSWORD = "Brand-New-Passw0rd"


def url(name):
    return reverse(f"accounts:{name}")


def account(email=EMAIL):
    profile = make_student()
    user = claim(profile, PASSWORD, contact_email=email)
    return profile, user


def fresh_client():
    return Client(HTTP_ACCEPT_LANGUAGE="en")


def strip_csrf(response):
    """The page without its per-request tokens (CSRF and CSP nonce)."""
    return re.sub(r'(value|content|nonce)="[A-Za-z0-9_-]{16,}"', r'=""', response.content.decode())


def wrong_code(real):
    return "000000" if real != "000000" else "111111"


# --- forgot password ----------------------------------------------------------------------------


def request_reset(web, identifier):
    return web.post(url("password_forgot"), {"identifier": identifier})


def test_password_reset_end_to_end(web, sent):
    _, user = account()
    web.post(url("login"), {"username": user.username, "password": PASSWORD})
    assert ActiveSession.objects.filter(user=user).exists()
    web.post(url("logout"))
    for _attempt in range(5):  # locked out first: a reset must also clear the lock
        web.post(url("login"), {"username": user.username, "password": "Wrong-password-1"})

    assert request_reset(web, user.username)["Location"] == url("password_forgot_verify")
    assert sent[-1].destination == EMAIL
    assert sent[-1].channel == "email"
    assert web.post(url("password_forgot_verify"), {"code": sent[-1].code})["Location"] == url(
        "password_forgot_new"
    )
    done = web.post(
        url("password_forgot_new"), {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD}
    )
    assert done["Location"] == url("login")

    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)
    assert not user.check_password(PASSWORD)
    assert (
        web.post(url("login"), {"username": user.username, "password": NEW_PASSWORD}).status_code
        == 302
    )
    assert AuditEvent.objects.filter(action="auth.password_reset", actor_id=user.pk).exists()


def test_reset_works_with_the_student_id_too(web, sent):
    profile, _user = account()
    request_reset(web, profile.registry.external_id)
    assert sent[-1].destination == EMAIL


def test_reset_signs_out_existing_sessions(web, sent):
    _, user = account()
    web.post(url("login"), {"username": user.username, "password": PASSWORD})
    ActiveSession.objects.get(user=user)
    request_reset(web, user.username)
    web.post(url("password_forgot_verify"), {"code": sent[-1].code})
    web.post(url("password_forgot_new"), {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD})
    assert not ActiveSession.objects.filter(user=user).exists()


@pytest.mark.parametrize("kind", ["unknown", "inactive", "no_contact"])
def test_unknown_inactive_and_contactless_accounts_get_the_same_answer(web, sent, kind):
    _, user = account()
    _, real = account("someone.else@example.com")
    if kind == "unknown":
        identifier = "stu_nobody1"
    elif kind == "inactive":
        User.objects.filter(pk=user.pk).update(is_active=False)
        identifier = user.username
    else:
        identifier = claim(make_student()).username  # signed up, but no contact on file

    real_client, other_client = fresh_client(), fresh_client()
    with CaptureQueriesContext(connection) as for_real:
        known = request_reset(real_client, real.username)
    with CaptureQueriesContext(connection) as for_other:
        other = request_reset(other_client, identifier)

    assert known.status_code == other.status_code == 302
    assert known["Location"] == other["Location"]
    assert len(for_real) == len(for_other)
    assert len(sent) == 1  # only the real account was written to
    assert strip_csrf(real_client.get(url("password_forgot_verify"))) == strip_csrf(
        other_client.get(url("password_forgot_verify"))
    )


def test_any_code_fails_for_an_unknown_account_just_like_a_wrong_one(web, sent):
    request_reset(web, "stu_nobody1")
    messages = set()
    for _attempt in range(5):
        response = web.post(url("password_forgot_verify"), {"code": "123456"})
        messages.add(tuple(response.context["form"].errors["code"]))
    assert messages == {("That code is not correct.",)}
    locked = web.post(url("password_forgot_verify"), {"code": "123456"})
    assert locked.context["form"].errors["code"] == ["Too many wrong attempts. Send a new code."]


def test_real_account_hits_the_same_attempt_limit(web, sent):
    _, user = account()
    request_reset(web, user.username)
    real = sent[-1].code
    for _attempt in range(5):
        response = web.post(url("password_forgot_verify"), {"code": wrong_code(real)})
        assert response.context["form"].errors["code"] == ["That code is not correct."]
    locked = web.post(url("password_forgot_verify"), {"code": real})
    assert locked.context["form"].errors["code"] == ["Too many wrong attempts. Send a new code."]


def test_expired_reset_code_is_refused(web, sent):
    _, user = account()
    request_reset(web, user.username)
    OneTimeCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    response = web.post(url("password_forgot_verify"), {"code": sent[-1].code})
    assert response.context["form"].errors["code"] == ["This code has expired. Send a new code."]


def test_resend_cooldown_and_new_message(web, sent):
    _, user = account()
    request_reset(web, user.username)
    early = web.post(url("password_forgot_resend"))
    assert "Please wait" in early.content.decode()
    assert len(sent) == 1
    OneTimeCode.objects.update(sent_at=timezone.now() - timedelta(seconds=61))
    web.post(url("password_forgot_resend"))
    assert len(sent) == 2
    assert sent[-1].destination == EMAIL


def test_resend_for_an_unknown_account_has_the_same_cooldown(web, sent):
    request_reset(web, "stu_nobody1")
    early = web.post(url("password_forgot_resend"))
    assert "Please wait" in early.content.decode()
    OneTimeCode.objects.update(sent_at=timezone.now() - timedelta(seconds=61))
    later = web.post(url("password_forgot_resend"))
    assert "A new code was sent." in later.content.decode()
    assert sent == []


def test_new_password_page_needs_a_verified_code(web, sent):
    assert web.get(url("password_forgot_new"))["Location"] == url("password_forgot")
    _, user = account()
    request_reset(web, user.username)
    assert web.get(url("password_forgot_new"))["Location"] == url("password_forgot")
    assert web.get(url("password_forgot_verify")).status_code == 200


def test_verify_page_without_a_started_reset_goes_back_to_the_start(web):
    assert web.get(url("password_forgot_verify"))["Location"] == url("password_forgot")
    assert web.post(url("password_forgot_resend"))["Location"] == url("password_forgot")


def test_reset_enforces_the_password_rules(web, sent):
    admin = make_admin(PASSWORD, contact_email="boss@example.com")
    enable_totp(admin)
    request_reset(web, admin.username)
    web.post(url("password_forgot_verify"), {"code": sent[-1].code})
    weak = "Abcdefg1234"
    response = web.post(url("password_forgot_new"), {"password1": weak, "password2": weak})
    assert "password1" in response.context["form"].errors
    admin.refresh_from_db()
    assert admin.check_password(PASSWORD)


def test_reset_does_not_bypass_the_second_factor(web, sent):
    admin = make_admin(PASSWORD, contact_email="boss@example.com")
    enable_totp(admin)
    request_reset(web, admin.username)
    web.post(url("password_forgot_verify"), {"code": sent[-1].code})
    web.post(url("password_forgot_new"), {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD})
    response = web.post(url("login"), {"username": admin.username, "password": NEW_PASSWORD})
    assert response["Location"] == url("login_second_factor")
    assert "_auth_user_id" not in web.session


def test_forgot_password_is_rate_limited_per_identifier_and_per_ip(web):
    per_identifier = [
        request_reset_from(web, "stu_target1", f"198.51.100.{n}").status_code for n in range(1, 7)
    ]
    assert per_identifier[:4] == [302] * 4
    assert per_identifier[4:] == [429, 429]
    per_ip = [
        request_reset_from(web, f"stu_n{n:04d}", "203.0.113.5").status_code for n in range(12)
    ]
    assert per_ip[:10] == [302] * 10
    assert per_ip[10:] == [429, 429]


def request_reset_from(web, identifier, ip):
    return web.post(url("password_forgot"), {"identifier": identifier}, REMOTE_ADDR=ip)


# --- forgot username ----------------------------------------------------------------------------


def test_username_recovery_shows_the_username_after_the_code(web, sent):
    profile, user = account()
    response = web.post(url("username_forgot"), {"registry_id": profile.registry.external_id})
    assert response["Location"] == url("username_forgot_verify")
    assert user.username not in web.get(url("username_forgot_verify")).content.decode()
    shown = web.post(url("username_forgot_verify"), {"code": sent[-1].code})
    assert user.username in shown.content.decode()
    assert AuditEvent.objects.filter(action="auth.username_recovered").exists()
    again = web.post(url("username_forgot_verify"), {"code": sent[-1].code})
    assert again["Location"] == url("username_forgot")  # shown once


def test_username_recovery_for_an_unknown_id_looks_the_same_and_shows_nothing(web, sent):
    account()
    response = web.post(url("username_forgot"), {"registry_id": "9999999"})
    assert response["Location"] == url("username_forgot_verify")
    result = web.post(url("username_forgot_verify"), {"code": "123456"})
    assert result.status_code == 200
    assert result.context["form"].errors["code"] == ["That code is not correct."]
    assert sent == []


def test_username_recovery_needs_the_id_not_the_username(web, sent):
    _, user = account()
    web.post(url("username_forgot"), {"registry_id": user.username})
    assert sent == []


def test_forgot_username_is_rate_limited(web):
    statuses = [
        web.post(
            url("username_forgot"), {"registry_id": "2100001"}, REMOTE_ADDR=f"198.51.100.{n}"
        ).status_code
        for n in range(1, 7)
    ]
    assert statuses[:4] == [302] * 4
    assert statuses[4:] == [429, 429]


# --- housekeeping -------------------------------------------------------------------------------


def test_purge_command_deletes_old_challenges(web, sent, capsys):
    _, user = account()
    request_reset(web, user.username)
    OneTimeCode.objects.update(created_at=timezone.now() - timedelta(days=3))
    call_command("purge_one_time_codes")
    assert "Deleted 1 one-time codes." in capsys.readouterr().out
    assert not OneTimeCode.objects.exists()
