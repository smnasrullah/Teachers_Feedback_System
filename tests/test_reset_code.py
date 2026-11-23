"""Forgotten password without e-mail or authenticator: a one-time reset code issued by the Admin
(any account) or a head of department (their own department), then ID + code + new password."""

import json
import logging
from datetime import timedelta

import pytest
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import IdRegistry, RegistryStatus, User
from apps.accounts.services import activation, signup
from apps.accounts.services import registry as registry_service
from apps.auditlog.models import AuditEvent
from apps.core.models import ActiveSession
from tests.auth_helpers import enable_totp
from tests.factories import (
    DepartmentFactory,
    claim,
    make_admin,
    make_hod,
    make_student,
    make_teacher,
    sign_in,
)

pytestmark = pytest.mark.django_db

OLD = "Old-Passw0rd!xyz"
NEW = "New-Passw0rd!xyz"
GENERIC = "The ID or reset code is not valid, or it has already been used."


def url(name, *args):
    return reverse(f"accounts:{name}", args=args)


def student_account(department=None):
    profile = make_student(department)
    return profile, claim(profile, OLD)


def issue(web, issuer, account):
    """Issue a code through the issuer's screen; returns the response and the plaintext code."""
    sign_in(web, issuer)
    if issuer.role == "admin":
        response = web.post(url("user_reset_code", account.pk))
    else:
        response = web.post(url("reset_code"), {"registry_id": account.registry.external_id})
    issued = response.context["issued"] if response.status_code == 200 else None
    return response, issued.code if issued else None


def use_code(external_id, code, password=NEW):
    visitor = Client(HTTP_ACCEPT_LANGUAGE="en")
    checked = visitor.post(url("password_forgot"), {"registry_id": external_id, "reset_code": code})
    if checked.status_code != 302:
        return visitor, checked
    return visitor, visitor.post(
        url("password_forgot_new"), {"password1": password, "password2": password}
    )


# --- issuing ------------------------------------------------------------------------------------


def test_the_admin_issues_a_code_shown_once_and_stored_hashed(web):
    profile, account = student_account()
    response, code = issue(web, make_admin(), account)
    assert response.status_code == 200
    assert "no-store" in response["Cache-Control"]
    assert code in response.content.decode()
    row = IdRegistry.objects.get(pk=profile.registry_id)
    assert row.activation_code_hash == activation.hash_code(code)
    assert code not in json.dumps(list(IdRegistry.objects.values()), default=str)
    hours = (row.activation_expires_at - timezone.now()).total_seconds() / 3600
    assert 23.9 < hours <= 24
    assert User.objects.get(pk=account.pk).check_password(OLD)  # still works until used


def test_issuing_is_audited_without_the_code(web):
    _profile, account = student_account()
    admin = make_admin()
    _response, code = issue(web, admin, account)
    event = AuditEvent.objects.get(action="account.reset_code_issued")
    assert event.actor_id == admin.pk
    assert event.object_id == str(account.pk)
    assert code not in json.dumps(event.metadata)
    assert event.metadata["valid_hours"] == 24


def test_a_head_issues_for_their_own_department_only(web):
    department = DepartmentFactory()
    hod = make_hod(department)
    _own, own_account = student_account(department)
    _other, other_account = student_account(DepartmentFactory())
    teacher_profile = make_teacher(department)
    teacher_account = claim(teacher_profile, OLD)

    response, code = issue(web, hod, own_account)
    assert response.status_code == 200 and code
    response, code = issue(web, hod, teacher_account)
    assert response.status_code == 200 and code
    response, code = issue(web, hod, other_account)
    assert response.status_code == 404 and code is None
    assert AuditEvent.objects.filter(action="account.reset_code_issued").count() == 2


def test_a_head_cannot_use_the_admin_screen(web):
    department = DepartmentFactory()
    hod = make_hod(department)
    _profile, account = student_account(department)
    sign_in(web, hod)
    assert web.post(url("user_reset_code", account.pk)).status_code == 403


@pytest.mark.parametrize("role", ["student", "teacher"])
def test_students_and_teachers_cannot_issue_codes(web, role):
    profile = make_student() if role == "student" else make_teacher()
    sign_in(web, claim(profile, OLD))
    assert web.get(url("reset_code")).status_code == 403
    assert web.post(url("reset_code"), {"registry_id": "X"}).status_code == 403


def test_no_code_for_oneself_an_admin_or_a_revoked_entry(web):
    admin = make_admin()
    other_admin = make_admin()
    profile, account = student_account()
    registry_service.revoke(IdRegistry.objects.filter(pk=profile.registry_id), actor=admin)
    for target in (admin, other_admin, User.objects.get(pk=account.pk)):
        assert not registry_service.can_issue_reset_code(target, admin)
    sign_in(web, admin)
    response = web.post(url("user_reset_code", other_admin.pk))
    assert response.status_code == 302
    assert not AuditEvent.objects.filter(action="account.reset_code_issued").exists()


def test_the_admin_user_page_offers_the_code_not_a_reset_access(web):
    _profile, account = student_account()
    sign_in(web, make_admin())
    html = web.get(url("user_detail", account.pk)).content.decode()
    assert url("user_reset_code", account.pk) in html
    assert "Issue reset code" in html
    assert "Reset access" not in html


# --- using it -----------------------------------------------------------------------------------


def test_the_code_sets_a_new_password_once_and_ends_every_session(web):
    profile, account = student_account()
    _response, code = issue(web, make_admin(), account)
    victim_device = Client(HTTP_ACCEPT_LANGUAGE="en")
    sign_in(victim_device, account)
    assert ActiveSession.objects.filter(user=account).exists()

    visitor, done = use_code(profile.registry.external_id, code)
    assert done.status_code == 302 and done["Location"] == url("login")
    user = User.objects.get(pk=account.pk)
    assert user.check_password(NEW)
    assert not ActiveSession.objects.filter(user=user).exists()
    assert victim_device.get(url("dashboard_student")).status_code == 302  # signed out
    row = IdRegistry.objects.get(pk=profile.registry_id)
    assert row.activation_code_hash == "" and row.activation_used_at is not None
    assert row.status == RegistryStatus.CLAIMED
    event = AuditEvent.objects.get(action="auth.password_reset")
    assert event.metadata["via"] == "reset_code"

    login = visitor.post(url("login"), {"username": user.username, "password": NEW})
    assert login.status_code == 302 and login["Location"] == url("dashboard_student")

    _visitor, reused = use_code(profile.registry.external_id, code, "Third-Passw0rd!x")
    assert reused.status_code == 200
    assert GENERIC in reused.content.decode()
    assert User.objects.get(pk=account.pk).check_password(NEW)


def test_an_expired_code_gets_the_generic_answer(web):
    profile, account = student_account()
    _response, code = issue(web, make_admin(), account)
    IdRegistry.objects.filter(pk=profile.registry_id).update(
        activation_expires_at=timezone.now() - timedelta(minutes=1)
    )
    _visitor, response = use_code(profile.registry.external_id, code)
    assert GENERIC in response.content.decode()
    assert User.objects.get(pk=account.pk).check_password(OLD)


def test_wrong_code_unknown_id_and_unclaimed_id_get_the_same_answer(web):
    profile, account = student_account()
    _response, code = issue(web, make_admin(), account)
    unclaimed = make_student()
    answers = [
        use_code(profile.registry.external_id, "AAAA-BBBB-CCCC")[1],
        use_code("NO-SUCH-ID-1", code)[1],
        use_code(unclaimed.registry.external_id, code)[1],
    ]
    for answer in answers:
        assert answer.status_code == 200
        assert answer.context["form"].non_field_errors() == [GENERIC]


def test_a_sign_up_code_is_not_a_reset_code_and_the_other_way_round(web):
    profile, account = student_account()
    _response, code = issue(web, make_admin(), account)
    assert signup.find_claimable(profile.registry.external_id, code) is None
    fresh = make_student()
    signup_code = registry_service.issue_activation_codes(
        IdRegistry.objects.filter(pk=fresh.registry_id), valid_days=1, actor=make_admin()
    )[0].code
    _visitor, response = use_code(fresh.registry.external_id, signup_code)
    assert GENERIC in response.content.decode()


def test_the_new_password_must_follow_the_rules(web):
    profile, account = student_account()
    _response, code = issue(web, make_admin(), account)
    _visitor, response = use_code(profile.registry.external_id, code, "123456789012")
    assert response.status_code == 200
    assert response.context["form"].errors["password1"]
    assert User.objects.get(pk=account.pk).check_password(OLD)


def test_the_reset_form_is_rate_limited(web):
    profile, _account = student_account()
    statuses = [
        web.post(
            url("password_forgot"),
            {"registry_id": profile.registry.external_id, "reset_code": f"AAAA-BBBB-{n:04d}"},
        ).status_code
        for n in range(8)
    ]
    assert 429 in statuses


def test_the_code_never_reaches_the_logs(web, caplog):
    caplog.set_level(logging.DEBUG)
    profile, account = student_account()
    _response, code = issue(web, make_admin(), account)
    use_code(profile.registry.external_id, code)
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert code not in logged
    assert code.replace("-", "") not in logged
    assert profile.registry.external_id not in logged
    assert NEW not in logged


@override_settings(TOTP_REQUIRED_ROLES=frozenset({"student"}))
def test_a_reset_forgets_the_authenticator_of_a_role_that_needs_one(web):
    profile, account = student_account()
    enable_totp(account)
    _response, code = issue(web, make_admin(), account)
    visitor, _done = use_code(profile.registry.external_id, code)
    user = User.objects.get(pk=account.pk)
    assert not user.totp_enabled and user.totp_secret is None
    login = visitor.post(url("login"), {"username": user.username, "password": NEW})
    assert login["Location"] == url("login_two_factor_setup")
