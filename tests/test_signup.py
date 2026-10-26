import logging
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import EMAIL_INDEX_PURPOSE, IdRegistry, OneTimeCode, RegistryStatus, User
from apps.accounts.services import registry as registry_service
from apps.auditlog.models import AuditEvent
from apps.core.encryption import blind_index
from apps.core.permissions import Role
from tests.auth_helpers import claimable_student, claimable_teacher
from tests.factories import claim, make_admin, make_student

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ng-Passw0rd!x"
EMAIL = "new.student@example.com"
GENERIC = "The ID or code is not valid, or it has already been used. Check both and try again."


def email_index():
    return blind_index(EMAIL, EMAIL_INDEX_PURPOSE)


def user_by_email():
    return User.objects.get(contact_email_index=email_index())


def url(name):
    return reverse(f"accounts:{name}")


def start_claim(web, profile, code, **extra):
    return web.post(
        url("signup"),
        {"registry_id": profile.registry.external_id, "activation_code": code},
        **extra,
    )


def to_verify(web, profile, code, sent):
    assert start_claim(web, profile, code).context["stage"] == "contact"
    response = web.post(url("signup_contact"), {"contact": EMAIL})
    assert response.context["stage"] == "verify"
    return sent[-1].code


def finish(web, profile, code, sent, password=PASSWORD):
    otp_code = to_verify(web, profile, code, sent)
    assert web.post(url("signup_verify"), {"code": otp_code}).context["stage"] == "password"
    return web.post(url("signup_password"), {"password1": password, "password2": password})


def test_full_signup_creates_account_claims_registry_and_burns_code(web, sent):
    profile, code = claimable_student()
    response = finish(web, profile, code, sent)

    user = user_by_email()
    assert user.role == Role.STUDENT
    assert user.department_id == profile.registry.department_id
    assert user.check_password(PASSWORD)
    assert response.context["done"] is True
    assert user.username in response.content.decode()
    registry = IdRegistry.objects.get(pk=profile.registry_id)
    assert registry.status == RegistryStatus.CLAIMED
    assert registry.claimed_by_id == user.pk
    assert registry.activation_code_hash == ""
    assert registry.activation_used_at is not None
    assert sent[0].destination == EMAIL
    event = AuditEvent.objects.get(action="auth.signup")
    assert event.actor_id == user.pk
    assert event.metadata == {"id_type": "student", "channel": "email"}


def test_code_cannot_be_reused_after_signup(web, sent):
    profile, code = claimable_student()
    finish(web, profile, code, sent)
    web.session.flush()
    again = start_claim(web, profile, code)
    assert again.context["form"].non_field_errors() == [GENERIC]


def test_teacher_id_creates_a_teacher(web, sent):
    profile, code = claimable_teacher()
    finish(web, profile, code, sent)
    assert user_by_email().role == Role.TEACHER


def test_username_is_shown_once_and_stays_on_the_account_page(web, sent):
    profile, code = claimable_student()
    finish(web, profile, code, sent)
    user = user_by_email()
    web.post(url("login"), {"username": user.username, "password": PASSWORD})
    assert user.username in web.get(url("account")).content.decode()


def test_nothing_secret_reaches_the_logs(web, sent, caplog):
    caplog.set_level(logging.DEBUG)
    profile, code = claimable_student()
    otp_code = to_verify(web, profile, code, sent)
    web.post(url("signup_verify"), {"code": otp_code})
    web.post(url("signup_password"), {"password1": PASSWORD, "password2": PASSWORD})
    logged = caplog.text
    for secret in (code, otp_code, PASSWORD):
        assert secret not in logged
    for event in AuditEvent.objects.all():
        assert code not in str(event.metadata)
        assert otp_code not in str(event.metadata)


def unknown(profile, code):
    return {"registry_id": "9999999", "activation_code": code}


def revoked(profile, code):
    registry_service.revoke(IdRegistry.objects.filter(pk=profile.registry_id), actor=make_admin())
    return None


def claimed(profile, code):
    claim(profile)
    return None


def wrong_code(profile, code):
    return {"activation_code": "AAAA-BBBB-CCCC"}


def expired(profile, code):
    IdRegistry.objects.filter(pk=profile.registry_id).update(
        activation_expires_at=timezone.now() - timedelta(seconds=1)
    )


def used(profile, code):
    IdRegistry.objects.filter(pk=profile.registry_id).update(activation_used_at=timezone.now())


@pytest.mark.parametrize("break_it", [unknown, revoked, claimed, wrong_code, expired, used])
def test_every_kind_of_bad_claim_gets_the_same_generic_error(web, break_it):
    profile, code = claimable_student()
    data = {"registry_id": profile.registry.external_id, "activation_code": code}
    override = break_it(profile, code)
    if override:
        data.update(override)
    response = web.post(url("signup"), data)
    assert response.status_code == 200
    assert response.context["stage"] == "claim"
    assert response.context["form"].non_field_errors() == [GENERIC]
    assert "signup" not in web.session


def test_unknown_and_known_ids_cost_the_same_queries(web):
    profile, _ = claimable_student()
    known = {"registry_id": profile.registry.external_id, "activation_code": "AAAA-BBBB-CCCC"}
    missing = {"registry_id": "9999999", "activation_code": "AAAA-BBBB-CCCC"}
    with CaptureQueriesContext(connection) as for_known:
        web.post(url("signup"), known)
    with CaptureQueriesContext(connection) as for_missing:
        web.post(url("signup"), missing)
    assert len(for_known) == len(for_missing)


def test_malformed_id_is_just_another_generic_failure(web):
    response = web.post(url("signup"), {"registry_id": "!!", "activation_code": "x"})
    assert response.context["form"].non_field_errors() == [GENERIC]


def test_htmx_gets_the_step_fragment_and_plain_requests_the_full_page(web):
    profile, code = claimable_student()
    data = {"registry_id": profile.registry.external_id, "activation_code": code}
    fragment = web.post(url("signup"), data, HTTP_HX_REQUEST="true").content.decode()
    assert "<html" not in fragment
    assert 'name="contact"' in fragment
    assert "stepper" in fragment
    web.session.flush()
    full = web.post(url("signup"), data).content.decode()
    assert "<html" in full
    assert 'id="signup-step"' in full


def test_contact_already_in_use_is_refused_without_sending_a_code(web, sent):
    claim(make_student(), contact_email=EMAIL)
    profile, code = claimable_student()
    start_claim(web, profile, code)
    response = web.post(url("signup_contact"), {"contact": EMAIL})
    assert response.context["stage"] == "contact"
    assert "contact" in response.context["form"].errors
    assert sent == []


def test_invalid_contact_is_refused(web, sent):
    profile, code = claimable_student()
    start_claim(web, profile, code)
    response = web.post(url("signup_contact"), {"contact": "not an address"})
    assert "contact" in response.context["form"].errors
    assert sent == []


def test_wrong_code_then_lockout_after_five_attempts(web, sent):
    profile, code = claimable_student()
    real = to_verify(web, profile, code, sent)
    wrong = "000000" if real != "000000" else "111111"
    for _attempt in range(5):
        response = web.post(url("signup_verify"), {"code": wrong})
        assert response.context["stage"] == "verify"
    locked = web.post(url("signup_verify"), {"code": real})
    assert locked.context["stage"] == "verify"
    assert "Too many wrong attempts" in locked.content.decode()


def test_expired_code_is_refused(web, sent):
    profile, code = claimable_student()
    real = to_verify(web, profile, code, sent)
    OneTimeCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    response = web.post(url("signup_verify"), {"code": real})
    assert "expired" in response.content.decode()
    assert response.context["stage"] == "verify"


def test_resend_respects_the_cooldown(web, sent):
    profile, code = claimable_student()
    to_verify(web, profile, code, sent)
    early = web.post(url("signup_resend"))
    assert "Please wait" in early.content.decode()
    assert len(sent) == 1
    OneTimeCode.objects.update(sent_at=timezone.now() - timedelta(seconds=61))
    later = web.post(url("signup_resend"))
    assert "A new code was sent." in later.content.decode()
    assert len(sent) == 2


def test_password_step_is_unreachable_before_the_code_is_verified(web, sent):
    profile, code = claimable_student()
    to_verify(web, profile, code, sent)
    response = web.post(url("signup_password"), {"password1": PASSWORD, "password2": PASSWORD})
    assert response.context["stage"] == "verify"
    assert not User.objects.filter(contact_email_index=email_index()).exists()


@pytest.mark.parametrize(
    ("first", "second"),
    [("short1A!", "short1A!"), (PASSWORD, PASSWORD + "x"), ("password", "password")],
)
def test_weak_or_mismatched_passwords_are_refused(web, sent, first, second):
    profile, code = claimable_student()
    otp_code = to_verify(web, profile, code, sent)
    web.post(url("signup_verify"), {"code": otp_code})
    response = web.post(url("signup_password"), {"password1": first, "password2": second})
    assert response.context["form"].errors
    assert not User.objects.filter(contact_email_index=email_index()).exists()


def test_revoking_the_id_mid_signup_stops_account_creation(web, sent):
    profile, code = claimable_student()
    otp_code = to_verify(web, profile, code, sent)
    web.post(url("signup_verify"), {"code": otp_code})
    registry_service.revoke(IdRegistry.objects.filter(pk=profile.registry_id), actor=make_admin())
    response = web.post(url("signup_password"), {"password1": PASSWORD, "password2": PASSWORD})
    assert response.context["stage"] == "claim"
    assert "could not be completed" in response.content.decode()
    assert not User.objects.filter(contact_email_index=email_index()).exists()


def test_two_people_cannot_claim_one_id(web, client, sent):
    profile, code = claimable_student()
    otp_code = to_verify(web, profile, code, sent)
    web.post(url("signup_verify"), {"code": otp_code})
    # Someone else finishes first.
    claim(profile)
    response = web.post(url("signup_password"), {"password1": PASSWORD, "password2": PASSWORD})
    assert response.context["stage"] == "claim"
    assert not User.objects.filter(contact_email_index=email_index()).exists()


@pytest.mark.parametrize("known", [True, False])
def test_claim_attempts_are_limited_per_id_for_known_and_unknown_ids(web, known):
    profile, _code = claimable_student()
    external_id = profile.registry.external_id if known else "7777777"
    statuses = [
        web.post(
            url("signup"),
            {"registry_id": external_id, "activation_code": "AAAA-BBBB-CCCC"},
            REMOTE_ADDR=f"198.51.100.{n}",
        ).status_code
        for n in range(1, 11)
    ]
    assert statuses[:8] == [200] * 8
    assert statuses[8:] == [429, 429]


def test_claim_attempts_are_limited_per_ip(web):
    statuses = [
        web.post(
            url("signup"),
            {"registry_id": f"90000{n:02d}", "activation_code": "AAAA-BBBB-CCCC"},
            REMOTE_ADDR="203.0.113.9",
        ).status_code
        for n in range(32)
    ]
    assert statuses[:30] == [200] * 30
    assert statuses[30:] == [429, 429]


def test_rate_limited_htmx_step_still_shows_the_message(web):
    for n in range(31):
        response = web.post(
            url("signup"),
            {"registry_id": f"80000{n:02d}", "activation_code": "AAAA-BBBB-CCCC"},
            REMOTE_ADDR="203.0.113.10",
            HTTP_HX_REQUEST="true",
        )
    assert response.status_code == 429
    assert "Too many attempts" in response.content.decode()
