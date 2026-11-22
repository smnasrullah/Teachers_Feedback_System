"""Log in / Create account exist only for visitors; a signed-in user sees their account instead."""

import re

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext

from apps.core.views import error_404
from tests.auth_helpers import enable_totp
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

ROLES = ["student", "teacher", "hod", "admin"]
LANGUAGES = ["en", "bn"]
GUEST_PAGES = [
    "accounts:login",
    "accounts:signup",
    "accounts:signup_password",
    "accounts:signup_authenticator",
    "accounts:password_forgot",
    "accounts:password_forgot_new",
    "accounts:username_forgot",
    "accounts:login_second_factor",
    "accounts:login_two_factor_setup",
]
HEADER = re.compile(r"<header class=\"nav.*?</header>", re.DOTALL)
STUDENT_ID = "2101777777"


def make_account(role: str):
    if role == "student":
        return claim(make_student(external_id=STUDENT_ID)), "accounts:dashboard_student"
    if role == "teacher":
        return claim(make_teacher()), "accounts:dashboard_teacher"
    if role == "hod":
        return make_hod(), "accounts:dashboard_hod"
    return make_admin(PASSWORD), "accounts:dashboard_admin"


def get(client, path: str, language: str):
    client.cookies["django_language"] = language
    return client.get(path)


def guest_markers(language: str) -> list[str]:
    with translation.override(language):
        return [f">{gettext('Log in')}<", f">{gettext('Create account')}<"]


def assert_guest_options_absent(html: str, language: str):
    for name in ("accounts:login", "accounts:signup"):
        assert f'href="{reverse(name)}' not in html
    for marker in guest_markers(language):
        assert marker not in html


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("role", ROLES)
def test_signed_in_pages_offer_no_log_in_or_sign_up(client, role, language):
    user, dashboard = make_account(role)
    sign_in(client, user)
    pages = [
        reverse("core:home"),
        reverse(dashboard),
        reverse("accounts:account"),
        "/no-such-page/",
    ]
    for path in pages:
        response = get(client, path, language)
        html = response.content.decode()

        assert response.status_code == (404 if path == "/no-such-page/" else 200), path
        assert_guest_options_absent(html, language)
        with translation.override(language):
            assert gettext("Log out") in html
        assert f'action="{reverse("accounts:logout")}" method="post"' in html
        assert f'href="{reverse(dashboard)}"' in html


@pytest.mark.parametrize("language", LANGUAGES)
def test_landing_for_a_signed_in_user_leads_to_the_dashboard(client, language):
    user, dashboard = make_account("teacher")
    sign_in(client, user)
    html = get(client, reverse("core:home"), language).content.decode()

    with translation.override(language):
        assert f">{gettext('Go to dashboard')}<" in html
    assert html.count(f'href="{reverse(dashboard)}"') >= 3


def test_header_names_the_person_by_nickname_or_username_never_the_student_id(client):
    user, _ = make_account("student")
    sign_in(client, user)

    header = HEADER.search(get(client, reverse("core:home"), "en").content.decode()).group()
    assert user.username in header
    assert "Student" in header
    assert STUDENT_ID not in header

    user.nickname = "Tuli"
    user.save()
    header = HEADER.search(get(client, reverse("core:home"), "en").content.decode()).group()
    assert "Tuli" in header
    assert user.username not in header
    assert STUDENT_ID not in header


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("path", ["core:home", "accounts:login", "accounts:signup"])
def test_anonymous_visitors_still_see_the_options(client, path, language):
    html = get(client, reverse(path), language).content.decode()

    assert guest_markers(language)[0] in html
    if path == "core:home":
        assert guest_markers(language)[1] in html
    if path == "accounts:login":
        assert f'href="{reverse("accounts:signup")}' in html
    else:
        assert f'href="{reverse("accounts:login")}' in html


def test_a_missing_page_for_a_visitor_shows_the_options(client):
    html = get(client, "/no-such-page/", "en").content.decode()

    assert f'href="{reverse("accounts:login")}' in html


def test_half_signed_in_session_is_treated_as_a_visitor(client):
    user = claim(make_student(), PASSWORD)
    enable_totp(user)
    login = client.post(
        reverse("accounts:login"), {"username": user.username, "password": PASSWORD}
    )
    assert login["Location"] == reverse("accounts:login_second_factor")

    assert client.get(reverse("accounts:login_second_factor")).status_code == 200
    assert client.get(reverse("accounts:login")).status_code == 200
    landing = client.get(reverse("core:home")).content.decode()
    assert f'href="{reverse("accounts:login")}' in landing
    assert reverse("accounts:logout") not in landing


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("name", GUEST_PAGES)
def test_signed_in_users_are_sent_to_their_dashboard_from_guest_pages(client, role, name):
    user, dashboard = make_account(role)
    sign_in(client, user)
    path = reverse(name) + "?next=https://evil.example/"

    responses = [client.get(path)]
    if name != "accounts:username_forgot":  # a help page: it only answers GET
        responses.append(client.post(path, {"next": "https://evil.example/"}))
    for response in responses:
        assert response.status_code == 302
        assert response["Location"] == reverse(dashboard)


def test_signing_out_brings_the_options_back_and_needs_a_post(client):
    user, _ = make_account("student")
    sign_in(client, user)

    assert client.get(reverse("accounts:logout")).status_code == 405
    response = client.post(reverse("accounts:logout"))
    assert response["Location"] == reverse("core:home")

    html = client.get(response["Location"]).content.decode()
    assert f'href="{reverse("accounts:login")}' in html
    assert f'href="{reverse("accounts:signup")}' in html
    assert reverse("accounts:logout") not in html


def test_signed_in_responses_are_never_cached_and_vary_on_the_cookie(client):
    user, dashboard = make_account("student")
    sign_in(client, user)

    for path in (reverse("core:home"), reverse(dashboard), "/no-such-page/"):
        response = client.get(path)
        assert "no-store" in response["Cache-Control"]
        assert "private" in response["Cache-Control"]
        assert "Cookie" in response["Vary"]


def test_an_error_page_without_a_user_to_ask_offers_only_home():
    request = RequestFactory().get("/no-such-page/")
    html = error_404(request).content.decode()

    assert_guest_options_absent(html, "en")
    assert f'href="{reverse("core:home")}"' in html


def test_an_error_page_for_an_anonymous_request_follows_the_visitor_rule():
    request = RequestFactory().get("/no-such-page/")
    request.user = AnonymousUser()
    html = error_404(request).content.decode()

    assert f'href="{reverse("accounts:login")}' in html
