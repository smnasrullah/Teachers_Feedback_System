"""Step-up: sensitive actions ask for the current password again (no code) once the last
password entry is more than ``STEP_UP_SECONDS`` old."""

import time
from urllib.parse import parse_qs, urlsplit

import pytest
from django.conf import settings
from django.urls import reverse

from apps.accounts.services.login import STEP_UP_KEY
from apps.auditlog.models import AuditEvent
from apps.core.permissions import Role
from tests.factories import claim, make_admin, make_hod, make_student, make_teacher, sign_in

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ng-Passw0rd!x"


def url(name, *args):
    return reverse(f"accounts:{name}", args=args)


def age_step_up(web, seconds):
    session = web.session
    session[STEP_UP_KEY] = int(time.time()) - seconds
    session.save()


@pytest.fixture
def admin_web(web):
    admin = make_admin(PASSWORD)
    sign_in(web, admin)
    age_step_up(web, settings.STEP_UP_SECONDS + 1)
    return web


def next_of(response) -> str:
    assert response.status_code == 302
    parts = urlsplit(response["Location"])
    assert parts.path == url("step_up")
    return parse_qs(parts.query)["next"][0]


def test_a_fresh_login_counts_as_a_confirmation(web):
    admin = make_admin(PASSWORD)
    web.post(url("login"), {"username": admin.username, "password": PASSWORD})
    account = claim(make_student())
    assert web.get(url("user_detail", account.pk)).status_code == 200


def test_after_ten_minutes_the_password_is_asked_again(web):
    admin = make_admin(PASSWORD)
    sign_in(web, admin)
    account = claim(make_student())
    age_step_up(web, settings.STEP_UP_SECONDS - 5)
    assert web.get(url("user_detail", account.pk)).status_code == 200
    age_step_up(web, settings.STEP_UP_SECONDS + 1)
    assert next_of(web.get(url("user_detail", account.pk))) == url("user_detail", account.pk)


def test_the_step_up_page_asks_for_the_password_only(admin_web):
    response = admin_web.get(url("step_up"))
    assert list(response.context["form"].fields) == ["password"]
    html = response.content.decode()
    assert 'autocomplete="one-time-code"' not in html
    assert "no-store" in response["Cache-Control"]


def test_the_right_password_opens_the_action_and_the_wrong_one_does_not(admin_web):
    account = claim(make_student())
    target = url("user_detail", account.pk)
    wrong = admin_web.post(url("step_up"), {"password": "not-my-password", "next": target})
    assert wrong.status_code == 200
    assert wrong.context["form"].errors["password"]
    assert next_of(admin_web.get(target)) == target
    right = admin_web.post(url("step_up"), {"password": PASSWORD, "next": target})
    assert right.status_code == 302 and right["Location"] == target
    assert admin_web.get(target).status_code == 200
    outcomes = list(
        AuditEvent.objects.filter(action="auth.step_up").values_list("metadata__outcome", flat=True)
    )
    assert outcomes == ["rejected", "ok"]


@pytest.mark.parametrize(
    "target", ["https://evil.example/phish", "//evil.example/", "http://testserver.evil/x"]
)
def test_next_cannot_leave_the_site(admin_web, target):
    response = admin_web.post(url("step_up"), {"password": PASSWORD, "next": target})
    assert response.status_code == 302
    assert response["Location"] == url("dashboard_admin")


def test_a_stale_post_changes_nothing_and_comes_back_to_its_page(admin_web):
    account = claim(make_teacher())
    detail = f"http://testserver{url('user_detail', account.pk)}"
    response = admin_web.post(
        url("user_role", account.pk), {"role": Role.ADMIN}, HTTP_REFERER=detail
    )
    assert next_of(response) == detail
    account.refresh_from_db()
    assert account.role == Role.TEACHER


def test_a_foreign_referer_is_not_used_as_next(admin_web):
    account = claim(make_teacher())
    response = admin_web.post(
        url("user_role", account.pk), {"role": Role.ADMIN}, HTTP_REFERER="https://evil.example/"
    )
    assert next_of(response) == url("dashboard_admin")


def test_issuing_a_reset_code_needs_a_fresh_password(admin_web):
    account = claim(make_student())
    response = admin_web.post(url("user_reset_code", account.pk))
    next_of(response)
    assert not AuditEvent.objects.filter(action="account.reset_code_issued").exists()


@pytest.mark.parametrize(
    "path",
    [
        lambda: reverse("accounts:reset_code"),
        lambda: reverse("reports:export_pending", kwargs={"fmt": "csv"}),
    ],
)
def test_reset_codes_and_id_exports_need_a_fresh_password_for_a_head(web, path):
    hod = make_hod()
    sign_in(web, hod)
    age_step_up(web, settings.STEP_UP_SECONDS + 1)
    next_of(web.get(path()))


def test_the_promotion_run_and_bulk_codes_need_a_fresh_password(admin_web):
    response = admin_web.get(reverse("academics:promotion_confirm", args=[1]))
    next_of(response)
    response = admin_web.post(url("registry_bulk"), {"action": "issue_codes"})
    next_of(response)


def test_wrong_step_up_passwords_count_towards_the_lockout(web):
    user = claim(make_student(), PASSWORD)
    sign_in(web, user)
    for _ in range(settings.AXES_FAILURE_LIMIT):
        web.post(url("step_up"), {"password": "wrong-password-1"})
    locked = web.post(url("step_up"), {"password": PASSWORD})
    assert locked.status_code == 429
