import time

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.models import User
from apps.auditlog.models import AuditEvent
from apps.core.models import ActiveSession
from apps.core.services.sessions import SECOND_FACTOR_KEY
from tests.auth_helpers import enable_totp, totp_code
from tests.factories import (
    PASSWORD,
    claim,
    make_admin,
    make_hod,
    make_student,
    make_teacher,
    sign_in,
)

pytestmark = pytest.mark.django_db

GENERIC = "The username or password is not correct."


def url(name, *args):
    return reverse(f"accounts:{name}", args=args)


def with_password(user):
    user.set_password(PASSWORD)
    user.save()
    return user


def student():
    return with_password(claim(make_student()))


def teacher():
    return with_password(claim(make_teacher()))


def hod():
    return with_password(make_hod())


def admin():
    return make_admin(PASSWORD)


def log_in(web, user, password=PASSWORD, **extra):
    return web.post(url("login"), {"username": user.username, "password": password}, **extra)


def is_signed_in(web) -> bool:
    return "_auth_user_id" in web.session


def second_step(web, user, code=None, **extra):
    """Finish a pending login with the next-step TOTP code (the enrolment code is used up)."""
    return web.post(
        url("login_second_factor"), {"code": code or totp_code(user, steps_ahead=1)}, **extra
    )


# --- password login ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("make", "destination"),
    [
        (student, "dashboard_student"),
        (teacher, "dashboard_teacher"),
    ],
)
def test_plain_roles_land_on_their_own_dashboard(web, make, destination):
    user = make()
    response = log_in(web, user)
    assert response.status_code == 302
    assert response["Location"] == url(destination)
    page = web.get(response["Location"])
    assert page.status_code == 200
    assert user.username in page.content.decode()
    assert AuditEvent.objects.filter(action="auth.login", actor_id=user.pk).exists()


@pytest.mark.parametrize(
    ("make", "destination"), [(hod, "dashboard_hod"), (admin, "dashboard_admin")]
)
def test_hod_and_admin_land_on_their_dashboard_after_totp(web, make, destination):
    user = make()
    enable_totp(user)
    assert log_in(web, user)["Location"] == url("login_second_factor")
    assert not is_signed_in(web)
    response = second_step(web, user)
    assert response["Location"] == url(destination)
    assert web.get(response["Location"]).status_code == 200


def test_dashboard_redirect_sends_each_role_home(web):
    user = student()
    web.post(url("login"), {"username": user.username, "password": PASSWORD})
    assert web.get(url("dashboard"))["Location"] == url("dashboard_student")


def test_a_student_cannot_open_other_roles_dashboards(web):
    log_in(web, student())
    for name in ("dashboard_teacher", "dashboard_hod", "dashboard_admin"):
        assert web.get(url(name)).status_code == 403


def test_wrong_password_and_unknown_username_look_identical(web):
    user = student()
    with CaptureQueriesContext(connection) as known:
        wrong = log_in(web, user, "Wrong-password-1")
    with CaptureQueriesContext(connection) as missing:
        unknown = web.post(url("login"), {"username": "stu_nobody", "password": "Wrong-password-1"})
    for response in (wrong, unknown):
        assert response.status_code == 200
        assert response.context["form"].non_field_errors() == [GENERIC]
    assert len(known) == len(missing)


def test_disabled_account_gets_the_same_generic_error(web):
    user = student()
    User.objects.filter(pk=user.pk).update(is_active=False)
    response = log_in(web, user)
    assert response.context["form"].non_field_errors() == [GENERIC]


def test_lockout_after_repeated_failures_even_with_the_right_password(web):
    user = student()
    for _attempt in range(5):
        log_in(web, user, "Wrong-password-1")
    locked = log_in(web, user)
    assert locked.status_code == 429
    assert "Too many failed attempts" in locked.content.decode()
    assert not is_signed_in(web)
    assert AuditEvent.objects.filter(action="auth.lockout").exists()
    assert AuditEvent.objects.filter(action="auth.login_failed").count() >= 5


def test_unknown_usernames_lock_out_exactly_like_real_ones(web):
    responses = [
        web.post(url("login"), {"username": "stu_ghost", "password": "Wrong-password-1"})
        for _attempt in range(6)
    ]
    assert responses[-1].status_code == 429
    assert "Too many failed attempts" in responses[-1].content.decode()


def test_audit_never_stores_the_typed_username_or_password(web):
    log_in(web, student(), "Typed-secret-1")
    web.post(url("login"), {"username": "stu_probe99", "password": "Typed-secret-2"})
    for event in AuditEvent.objects.filter(action="auth.login_failed"):
        text = str(event.metadata)
        assert "stu_probe99" not in text
        assert "Typed-secret" not in text
        assert event.metadata["username_ref"]


def test_login_is_rate_limited_per_ip(web):
    statuses = [
        web.post(
            url("login"),
            {"username": f"stu_x{n:04d}", "password": "Wrong-password-1"},
            REMOTE_ADDR="203.0.113.77",
        ).status_code
        for n in range(32)
    ]
    assert statuses[:30] == [200] * 30
    assert 429 in statuses[30:]


def test_login_is_rate_limited_per_username_across_ips(web):
    statuses = [
        web.post(
            url("login"),
            {"username": "stu_target1", "password": "Wrong-password-1"},
            REMOTE_ADDR=f"198.51.100.{n}",
        ).status_code
        for n in range(1, 13)
    ]
    assert statuses[:10] == [200] * 10
    assert statuses[10:] == [429, 429]


def test_next_is_followed_only_inside_the_site(web):
    user = student()
    assert log_in(web, user, next="/x")  # unknown extras are ignored
    web.post(url("logout"))
    inside = web.post(
        url("login"), {"username": user.username, "password": PASSWORD, "next": url("account")}
    )
    assert inside["Location"] == url("account")
    web.post(url("logout"))
    outside = web.post(
        url("login"),
        {"username": user.username, "password": PASSWORD, "next": "https://evil.example/"},
    )
    assert outside["Location"] == url("dashboard_student")


def test_signed_in_visitors_skip_the_login_page(web):
    log_in(web, student())
    assert web.get(url("login"))["Location"] == url("dashboard_student")


# --- second factor ------------------------------------------------------------------------------


def test_admin_without_totp_is_forced_to_enrol_and_is_not_signed_in_meanwhile(web):
    user = admin()
    response = log_in(web, user)
    assert response["Location"] == url("login_two_factor_setup")
    assert not is_signed_in(web)
    assert web.get(url("dashboard_admin"))["Location"].startswith(url("login"))

    page = web.get(url("login_two_factor_setup"))
    html = page.content.decode()
    assert "data:image/svg+xml" in html
    user.refresh_from_db()
    assert user.totp_secret and not user.totp_enabled
    assert len(page.context["manual_key"].replace(" ", "")) == len(user.totp_secret)

    bad = web.post(url("login_two_factor_setup"), {"code": "000000"})
    assert bad.status_code == 200
    assert not is_signed_in(web)

    done = web.post(url("login_two_factor_setup"), {"code": totp_code(user)})
    assert done.status_code == 200
    assert len(done.context["codes"]) == 8
    assert is_signed_in(web)
    assert web.session[SECOND_FACTOR_KEY]
    user.refresh_from_db()
    assert user.totp_enabled
    assert web.get(url("dashboard_admin")).status_code == 200
    assert AuditEvent.objects.filter(action="auth.twofactor_enabled", actor_id=user.pk).exists()


def test_recovery_codes_are_stored_hashed_only(web):
    user = admin()
    log_in(web, user)
    web.get(url("login_two_factor_setup"))
    user.refresh_from_db()
    codes = web.post(url("login_two_factor_setup"), {"code": totp_code(user)}).context["codes"]
    stored = " ".join(user.recovery_codes.values_list("code_hash", flat=True))
    for code in codes:
        assert code.replace("-", "") not in stored
    assert user.recovery_codes.count() == 8


@pytest.mark.parametrize("make", [hod, admin])
def test_hod_and_admin_cannot_reach_anything_without_totp(web, make):
    user = make()
    log_in(web, user)  # password only
    for name in ("dashboard", "dashboard_hod", "dashboard_admin", "account"):
        response = web.get(url(name))
        assert response.status_code == 302
        assert response["Location"].startswith(url("login"))
    assert not is_signed_in(web)


@pytest.mark.parametrize("make", [hod, admin])
def test_a_session_that_skipped_totp_is_ended(web, make):
    user = make()
    web.force_login(user)  # signed in without the second factor
    response = web.get(url("account"))
    assert response.status_code == 302
    assert response["Location"].startswith(url("login"))
    assert not is_signed_in(web)
    assert "complete two-factor" in web.get(url("login")).content.decode()


def test_totp_login_rejects_wrong_codes_and_audits_them(web):
    user = admin()
    enable_totp(user)
    log_in(web, user)
    response = second_step(web, user, "000000")
    assert response.status_code == 200
    assert response.context["form"].non_field_errors() == ["That code is not correct."]
    assert not is_signed_in(web)
    assert AuditEvent.objects.filter(
        action="auth.login_failed", metadata__stage="second_factor"
    ).exists()


def test_a_totp_code_works_only_once(web):
    user = admin()
    enable_totp(user)
    code = totp_code(user, steps_ahead=1)
    log_in(web, user)
    assert second_step(web, user, code).status_code == 302
    web.post(url("logout"))
    log_in(web, user)
    assert second_step(web, user, code).status_code == 200  # replay refused
    assert not is_signed_in(web)


def test_repeated_wrong_totp_codes_lock_the_account(web):
    user = admin()
    enable_totp(user)
    log_in(web, user)
    last = None
    for _attempt in range(5):
        last = second_step(web, user, "000000")
    assert last.status_code == 429
    assert AuditEvent.objects.filter(action="auth.lockout").exists()
    assert second_step(web, user).status_code == 429  # the right code is refused while locked


def test_recovery_code_works_exactly_once(web):
    user = admin()
    codes = enable_totp(user)
    log_in(web, user)
    assert second_step(web, user, codes[0]).status_code == 302
    assert is_signed_in(web)
    event = AuditEvent.objects.get(action="auth.recovery_code_used")
    assert event.metadata == {"remaining": 7}
    assert "7 recovery codes are left" in web.get(url("dashboard_admin")).content.decode()
    web.post(url("logout"))

    log_in(web, user)
    assert second_step(web, user, codes[0]).status_code == 200  # burned
    assert not is_signed_in(web)
    assert second_step(web, user, codes[1].lower().replace("-", " ")).status_code == 302


def test_pending_login_expires(web, settings):
    user = admin()
    enable_totp(user)
    log_in(web, user)
    session = web.session
    session["_tfs_pending_login"]["at"] = (
        int(time.time()) - settings.SECOND_FACTOR_PENDING_SECONDS - 5
    )
    session.save()
    assert web.get(url("login_second_factor"))["Location"] == url("login")


def test_second_factor_pages_need_a_pending_login(web):
    assert web.get(url("login_second_factor"))["Location"] == url("login")
    assert web.get(url("login_two_factor_setup"))["Location"] == url("login")


def test_students_can_turn_two_factor_on_and_then_must_use_it(web):
    user = student()
    log_in(web, user)
    page = web.get(url("two_factor_setup"))
    assert "data:image/svg+xml" in page.content.decode()
    user.refresh_from_db()
    done = web.post(url("two_factor_setup"), {"code": totp_code(user)})
    assert len(done.context["codes"]) == 8
    web.post(url("logout"))
    user.refresh_from_db()
    assert log_in(web, user)["Location"] == url("login_second_factor")
    assert second_step(web, user)["Location"] == url("dashboard_student")


def test_students_can_turn_two_factor_off_with_their_password(web):
    user = student()
    enable_totp(user)
    sign_in(web, user)
    refused = web.post(url("two_factor_disable"), {"password": "Wrong-password-1"})
    assert refused.status_code == 302
    user.refresh_from_db()
    assert user.totp_enabled
    web.post(url("two_factor_disable"), {"password": PASSWORD})
    user.refresh_from_db()
    assert not user.totp_enabled
    assert user.totp_secret is None
    assert user.recovery_codes.count() == 0
    assert AuditEvent.objects.filter(action="auth.twofactor_disabled").exists()


def test_admin_cannot_turn_two_factor_off(web):
    user = admin()
    enable_totp(user)
    sign_in(web, user)
    web.post(url("two_factor_disable"), {"password": PASSWORD})
    user.refresh_from_db()
    assert user.totp_enabled


def test_new_recovery_codes_replace_the_old_ones(web):
    user = admin()
    old = enable_totp(user)
    sign_in(web, user)
    response = web.post(url("two_factor_regenerate"), {"password": PASSWORD})
    assert len(response.context["codes"]) == 8
    assert not set(old) & set(response.context["codes"])
    assert AuditEvent.objects.filter(action="auth.recovery_codes_regenerated").exists()


# --- logout, sessions, password -----------------------------------------------------------------


def test_logout_needs_post(web):
    log_in(web, student())
    assert web.get(url("logout")).status_code == 405
    assert is_signed_in(web)
    assert web.post(url("logout"))["Location"] == url("login")
    assert not is_signed_in(web)


def test_log_out_all_devices_ends_every_session(web):
    user = student()
    log_in(web, user)
    assert ActiveSession.objects.filter(user=user).exists()
    web.post(url("sign_out_everywhere"))
    assert not ActiveSession.objects.filter(user=user).exists()
    assert not is_signed_in(web)
    assert AuditEvent.objects.filter(action="auth.sessions_revoked").exists()


def test_a_second_device_replaces_the_first(web):
    user = student()
    log_in(web, user)
    other = Client(HTTP_ACCEPT_LANGUAGE="en")
    log_in(other, user)
    assert web.get(url("account"))["Location"].startswith(url("login"))


def test_account_page_shows_username_contact_and_the_active_session(web):
    user = claim(make_student(), PASSWORD, contact_email="aminul.islam@example.com")
    log_in(web, user, HTTP_USER_AGENT="TestBrowser/1.0", REMOTE_ADDR="198.51.100.20")
    html = web.get(url("account")).content.decode()
    assert user.username in html
    assert "am***@example.com" in html
    assert "aminul.islam@example.com" not in html
    assert "TestBrowser/1.0" in html
    assert "198.51.100.20" in html


def test_password_change_keeps_this_session_and_audits(web):
    user = student()
    log_in(web, user)
    new = "Another-Str0ng-pass"
    wrong = web.post(
        url("password_change"),
        {"current_password": "Nope-nope-1", "password1": new, "password2": new},
    )
    assert "current_password" in wrong.context["form"].errors
    ok = web.post(
        url("password_change"),
        {"current_password": PASSWORD, "password1": new, "password2": new},
    )
    assert ok["Location"] == url("account")
    assert web.get(url("account")).status_code == 200  # still signed in
    user.refresh_from_db()
    assert user.check_password(new)
    assert AuditEvent.objects.filter(action="auth.password_changed", actor_id=user.pk).exists()


def test_admin_password_change_needs_a_strong_password(web):
    user = admin()
    enable_totp(user)
    sign_in(web, user)
    weak = "Abcdefg1234"  # 11 characters: fine for a student, too short for an admin
    response = web.post(
        url("password_change"),
        {"current_password": PASSWORD, "password1": weak, "password2": weak},
    )
    assert "password1" in response.context["form"].errors


def test_pages_that_need_login_send_anonymous_visitors_to_it(web):
    for name in ("account", "password_change", "two_factor", "dashboard"):
        assert web.get(url(name))["Location"].startswith(url("login"))
    for name in ("logout",):
        assert web.get(url(name)).status_code == 405


def test_auth_pages_are_available_in_bangla(client):
    client.defaults["HTTP_ACCEPT_LANGUAGE"] = "bn"
    login_page = client.get(url("login")).content.decode()
    assert "পাসওয়ার্ড ভুলে গেছেন?" in login_page
    assert "Forgot your password?" not in login_page
    signup_page = client.get(url("signup")).content.decode()
    assert "আইডি ও কোড" in signup_page
    failed = client.post(url("login"), {"username": "stu_nobody", "password": "x"})
    assert "ইউজারনেম বা পাসওয়ার্ড সঠিক নয়।" in failed.content.decode()
