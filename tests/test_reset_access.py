import csv
import io

import pytest
from django.core.management import CommandError, call_command
from django.test import Client
from django.urls import reverse

from apps.accounts.models import IdRegistry, RegistryStatus, User
from apps.accounts.services import registry as registry_service
from apps.accounts.services import signup as signup_service
from apps.auditlog.models import AuditEvent
from apps.core.models import ActiveSession
from tests.auth_helpers import code_for_secret, enable_totp, fresh_code
from tests.factories import PASSWORD, claim, make_admin, make_hod, make_student, sign_in

pytestmark = pytest.mark.django_db

NEW_PASSWORD = "Fresh-Start-Passw0rd"


def url(name, *args):
    return reverse(f"accounts:{name}", args=args)


@pytest.fixture
def admin_web(web):
    admin = make_admin(PASSWORD)
    enable_totp(admin)
    sign_in(web, admin)
    web.admin = admin
    return web


def student_with_phone():
    profile = make_student()
    user = claim(profile, PASSWORD)
    enable_totp(user)
    return profile, user


def reset(web, user, output="page", valid_days=7):
    return web.post(url("user_reset_access", user.pk), {"valid_days": valid_days, "output": output})


def test_reset_clears_password_authenticator_codes_and_sessions(admin_web):
    profile, user = student_with_phone()
    other = Client(HTTP_ACCEPT_LANGUAGE="en")
    sign_in(other, user)
    assert ActiveSession.objects.filter(user=user).exists()

    response = reset(admin_web, user)
    assert response.status_code == 200
    code = response.context["issued"].code
    assert code in response.content.decode()
    assert "Cache-Control" in response and "no-cache" in response["Cache-Control"]

    user.refresh_from_db()
    assert not user.has_usable_password()
    assert not user.totp_enabled and user.totp_secret is None
    assert not user.recovery_codes.exists()
    assert not ActiveSession.objects.filter(user=user).exists()
    assert other.get(url("account"))["Location"].startswith(url("login"))
    registry = IdRegistry.objects.get(pk=profile.registry_id)
    assert registry.status == RegistryStatus.CLAIMED
    assert registry.claimed_by_id == user.pk
    assert registry.activation_state == "active"
    event = AuditEvent.objects.get(action="account.access_reset")
    assert event.actor_id == admin_web.admin.pk
    assert event.object_id == str(user.pk)
    assert code not in str(event.metadata)


def test_the_old_password_and_phone_stop_working(admin_web):
    _profile, user = student_with_phone()
    reset(admin_web, user)
    web = Client(HTTP_ACCEPT_LANGUAGE="en")
    response = web.post(url("login"), {"username": user.username, "password": PASSWORD})
    assert response.status_code == 200
    assert "_tfs_pending_login" not in web.session


def test_the_person_re_enrols_with_the_new_code_and_keeps_the_username(admin_web):
    profile, user = student_with_phone()
    code = reset(admin_web, user).context["issued"].code

    web = Client(HTTP_ACCEPT_LANGUAGE="en")
    claimed = web.post(
        url("signup"), {"registry_id": profile.registry.external_id, "activation_code": code}
    )
    assert claimed.context["stage"] == "password"
    page = web.post(url("signup_password"), {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD})
    assert page.context["username"] == user.username
    secret = signup_service.unseal(web.session["signup"]["secret"])
    done = web.post(url("signup_authenticator"), {"code": code_for_secret(secret)})
    assert done.context["stage"] == "done"
    assert done.context["username"] == user.username
    assert len(done.context["codes"]) == 8

    assert User.objects.filter(pk=user.pk).count() == 1
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)
    assert user.totp_enabled and user.totp_secret == secret
    registry = IdRegistry.objects.get(pk=profile.registry_id)
    assert registry.activation_code_hash == "" and registry.activation_used_at is not None
    assert AuditEvent.objects.filter(action="auth.reenrolled", actor_id=user.pk).exists()

    again = Client(HTTP_ACCEPT_LANGUAGE="en")
    used = again.post(
        url("signup"), {"registry_id": profile.registry.external_id, "activation_code": code}
    )
    assert used.context["stage"] == "claim"


def test_a_claimed_id_without_a_reset_cannot_be_re_enrolled(web):
    profile, _user = student_with_phone()
    response = web.post(
        url("signup"),
        {"registry_id": profile.registry.external_id, "activation_code": "AAAA-BBBB-CCCC"},
    )
    assert response.context["stage"] == "claim"


def test_revoking_after_a_reset_closes_the_re_enrolment(admin_web):
    profile, user = student_with_phone()
    code = reset(admin_web, user).context["issued"].code
    registry_service.revoke(IdRegistry.objects.filter(pk=profile.registry_id), actor=make_admin())
    web = Client(HTTP_ACCEPT_LANGUAGE="en")
    response = web.post(
        url("signup"), {"registry_id": profile.registry.external_id, "activation_code": code}
    )
    assert response.context["stage"] == "claim"


def test_reset_works_for_a_head_of_department(admin_web):
    hod = make_hod()
    enable_totp(hod)
    assert reset(admin_web, hod).status_code == 200
    hod.refresh_from_db()
    assert not hod.totp_enabled


def test_reset_can_be_downloaded_as_csv(admin_web):
    profile, user = student_with_phone()
    response = reset(admin_web, user, output="csv")
    assert response["Content-Type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert rows[1][0] == profile.registry.external_id
    assert len(rows[1][3]) == 14  # XXXX-XXXX-XXXX


@pytest.mark.parametrize("target", ["admin", "self", "revoked"])
def test_reset_is_refused_for_admins_and_revoked_entries(admin_web, target):
    if target == "admin":
        account = make_admin(PASSWORD)
    elif target == "self":
        account = admin_web.admin
    else:
        profile, account = student_with_phone()
        registry_service.revoke(
            IdRegistry.objects.filter(pk=profile.registry_id), actor=admin_web.admin
        )
    detail = admin_web.get(url("user_detail", account.pk))
    assert detail.context["reset_form"] is None
    response = reset(admin_web, account)
    assert response["Location"] == url("user_detail", account.pk)
    assert not AuditEvent.objects.filter(action="account.access_reset").exists()


def test_only_the_admin_can_reset_access(web):
    _profile, user = student_with_phone()
    hod = make_hod()
    enable_totp(hod)
    sign_in(web, hod)
    assert reset(web, user).status_code == 403
    user.refresh_from_db()
    assert user.totp_enabled


def test_user_detail_offers_the_reset(admin_web):
    _profile, user = student_with_phone()
    html = admin_web.get(url("user_detail", user.pk)).content.decode()
    assert "Reset access" in html
    assert url("user_reset_access", user.pk) in html


# --- development helper -------------------------------------------------------------------------


def test_totp_code_prints_the_current_code_in_development(settings, capsys):
    settings.DEBUG = True
    settings.SETTINGS_MODULE = "config.settings.dev"  # set last: each override resets it
    _profile, user = student_with_phone()
    call_command("totp_code", user.username)
    printed = capsys.readouterr().out.strip()
    assert printed == fresh_code(user)


@pytest.mark.parametrize(
    ("module", "debug"),
    [
        ("config.settings.test", True),
        ("config.settings.prod", False),
        ("config.settings.dev", False),
    ],
)
def test_totp_code_refuses_outside_development(settings, capsys, module, debug):
    settings.DEBUG = debug
    settings.SETTINGS_MODULE = module
    _profile, user = student_with_phone()
    with pytest.raises(CommandError, match="DEBUG"):
        call_command("totp_code", user.username)
    assert capsys.readouterr().out == ""


def test_totp_code_needs_an_account_with_an_authenticator(settings):
    settings.DEBUG = True
    settings.SETTINGS_MODULE = "config.settings.dev"
    with pytest.raises(CommandError, match="No account"):
        call_command("totp_code", "stu_nobody1")
