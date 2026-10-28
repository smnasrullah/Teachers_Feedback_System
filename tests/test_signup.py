import logging
from datetime import timedelta

import pytest
from django.contrib.sessions.models import Session
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import IdRegistry, RegistryStatus, User
from apps.accounts.services import registry as registry_service
from apps.accounts.services import signup as signup_service
from apps.auditlog.models import AuditEvent
from apps.core.permissions import Role
from tests.auth_helpers import claimable_student, claimable_teacher, code_for_secret
from tests.factories import claim, make_admin

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ng-Passw0rd!x"
GENERIC = "The ID or code is not valid, or it has already been used. Check both and try again."


def url(name):
    return reverse(f"accounts:{name}")


def start_claim(web, profile, code, **extra):
    return web.post(
        url("signup"),
        {"registry_id": profile.registry.external_id, "activation_code": code},
        **extra,
    )


def to_authenticator(web, profile, code, password=PASSWORD):
    assert start_claim(web, profile, code).context["stage"] == "password"
    response = web.post(url("signup_password"), {"password1": password, "password2": password})
    assert response.context["stage"] == "authenticator"
    return response


def session_secret(web) -> str:
    return signup_service.unseal(web.session["signup"]["secret"])


def finish(web, profile, code):
    to_authenticator(web, profile, code)
    return web.post(url("signup_authenticator"), {"code": code_for_secret(session_secret(web))})


def account_of(profile) -> User | None:
    return IdRegistry.objects.get(pk=profile.registry_id).claimed_by


def test_full_signup_creates_an_account_with_its_authenticator(web):
    profile, code = claimable_student()
    page = to_authenticator(web, profile, code)
    secret = session_secret(web)
    response = web.post(url("signup_authenticator"), {"code": code_for_secret(secret)})

    user = account_of(profile)
    assert user.role == Role.STUDENT
    assert user.department_id == profile.registry.department_id
    assert user.check_password(PASSWORD)
    assert user.totp_enabled
    assert user.totp_secret == secret
    assert user.totp_last_step > 0  # the first code cannot be replayed at login
    assert user.contact_email is None and user.contact_phone is None
    assert user.username == page.context["username"]
    assert response.context["stage"] == "done"
    assert user.username in response.content.decode()
    codes = response.context["codes"]
    assert len(codes) == 8
    assert all(code in response.content.decode() for code in codes)
    stored = " ".join(user.recovery_codes.values_list("code_hash", flat=True))
    assert not any(code.replace("-", "") in stored for code in codes)
    registry = IdRegistry.objects.get(pk=profile.registry_id)
    assert registry.status == RegistryStatus.CLAIMED
    assert registry.activation_code_hash == ""
    assert registry.activation_used_at is not None
    event = AuditEvent.objects.get(action="auth.signup")
    assert event.actor_id == user.pk
    assert event.metadata == {"id_type": "student"}
    assert "signup" not in web.session


def test_authenticator_page_shows_qr_key_and_the_three_step_guide(web):
    profile, code = claimable_student()
    page = to_authenticator(web, profile, code)
    html = page.content.decode()
    assert "data:image/svg+xml" in html
    assert page.context["manual_key"].replace(" ", "") == session_secret(web)
    assert "Google Authenticator or Microsoft Authenticator" in html
    assert "Type the 6-digit code" in html
    again = web.get(url("signup_authenticator"))
    assert again.context["manual_key"] == page.context["manual_key"]  # the secret is kept


def test_no_account_exists_until_the_first_code_checks_out(web):
    profile, code = claimable_student()
    to_authenticator(web, profile, code)
    real = code_for_secret(session_secret(web))
    wrong = "000000" if real != "000000" else "111111"
    response = web.post(url("signup_authenticator"), {"code": wrong})
    assert response.context["stage"] == "authenticator"
    assert "That code is not correct" in response.content.decode()
    assert not User.objects.filter(role=Role.STUDENT).exists()
    assert IdRegistry.objects.get(pk=profile.registry_id).status == RegistryStatus.UNCLAIMED


def test_a_far_off_code_is_refused_but_neighbouring_steps_work(web):
    profile, code = claimable_student()
    to_authenticator(web, profile, code)
    secret = session_secret(web)
    far = web.post(url("signup_authenticator"), {"code": code_for_secret(secret, steps_ahead=3)})
    assert far.context["stage"] == "authenticator"
    near = web.post(url("signup_authenticator"), {"code": code_for_secret(secret, steps_ahead=-1)})
    assert near.context["stage"] == "done"


def test_password_and_secret_wait_encrypted_in_the_session(web):
    profile, code = claimable_student()
    to_authenticator(web, profile, code)
    secret = session_secret(web)
    session = Session.objects.get(session_key=web.session.session_key)
    stored = str(session.get_decoded())
    assert secret not in stored
    assert "argon2" not in stored
    assert PASSWORD not in stored
    assert signup_service.unseal(web.session["signup"]["password"]).startswith("argon2")


def test_code_cannot_be_reused_after_signup(web):
    profile, code = claimable_student()
    finish(web, profile, code)
    web.session.flush()
    again = start_claim(web, profile, code)
    assert again.context["form"].non_field_errors() == [GENERIC]


def test_teacher_id_creates_a_teacher(web):
    profile, code = claimable_teacher()
    finish(web, profile, code)
    assert account_of(profile).role == Role.TEACHER


def test_new_account_logs_in_with_password_and_code_and_sees_its_username(web):
    profile, code = claimable_student()
    finish(web, profile, code)
    user = account_of(profile)
    response = web.post(url("login"), {"username": user.username, "password": PASSWORD})
    assert response["Location"] == url("login_second_factor")
    secret = user.totp_secret
    web.post(url("login_second_factor"), {"code": code_for_secret(secret, steps_ahead=1)})
    assert user.username in web.get(url("account")).content.decode()


def test_nothing_secret_reaches_the_logs(web, caplog):
    caplog.set_level(logging.DEBUG)
    profile, code = claimable_student()
    to_authenticator(web, profile, code)
    secret = session_secret(web)
    totp = code_for_secret(secret)
    codes = web.post(url("signup_authenticator"), {"code": totp}).context["codes"]
    logged = caplog.text
    for value in (code, PASSWORD, secret, totp, *codes):
        assert value not in logged
    for event in AuditEvent.objects.all():
        for value in (code, secret, totp, *codes):
            assert value not in str(event.metadata)


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
    assert 'name="password1"' in fragment
    assert "stepper" in fragment
    web.session.flush()
    full = web.post(url("signup"), data).content.decode()
    assert "<html" in full
    assert 'id="signup-step"' in full


def test_later_steps_are_unreachable_before_the_earlier_ones(web):
    profile, code = claimable_student()
    early = web.post(url("signup_password"), {"password1": PASSWORD, "password2": PASSWORD})
    assert early.context["stage"] == "claim"
    start_claim(web, profile, code)
    skipped = web.post(url("signup_authenticator"), {"code": "123456"})
    assert skipped.context["stage"] == "password"
    assert not User.objects.filter(role=Role.STUDENT).exists()


@pytest.mark.parametrize(
    ("first", "second"),
    [("short1A!", "short1A!"), (PASSWORD, PASSWORD + "x"), ("password", "password")],
)
def test_weak_or_mismatched_passwords_are_refused(web, first, second):
    profile, code = claimable_student()
    start_claim(web, profile, code)
    response = web.post(url("signup_password"), {"password1": first, "password2": second})
    assert response.context["stage"] == "password"
    assert response.context["form"].errors
    assert "password" not in web.session["signup"]


def test_revoking_the_id_mid_signup_stops_account_creation(web):
    profile, code = claimable_student()
    to_authenticator(web, profile, code)
    secret = session_secret(web)
    registry_service.revoke(IdRegistry.objects.filter(pk=profile.registry_id), actor=make_admin())
    response = web.post(url("signup_authenticator"), {"code": code_for_secret(secret)})
    assert response.context["stage"] == "claim"
    assert "could not be completed" in response.content.decode()
    assert not User.objects.filter(role=Role.STUDENT).exists()


def test_two_people_cannot_claim_one_id(web):
    profile, code = claimable_student()
    to_authenticator(web, profile, code)
    secret = session_secret(web)
    claim(profile)  # someone else finishes first
    response = web.post(url("signup_authenticator"), {"code": code_for_secret(secret)})
    assert response.context["stage"] == "claim"
    assert User.objects.filter(role=Role.STUDENT).count() == 1  # only the first claimant


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


def test_authenticator_codes_are_rate_limited_per_session(web):
    profile, code = claimable_student()
    to_authenticator(web, profile, code)
    statuses = [
        web.post(url("signup_authenticator"), {"code": "000000"}).status_code for _ in range(14)
    ]
    assert statuses[:12] == [200] * 12
    assert statuses[12:] == [429, 429]


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
