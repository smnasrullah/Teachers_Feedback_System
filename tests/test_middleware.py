import re
import time

import pytest
from django.contrib.auth import login
from django.contrib.sessions.backends.db import SessionStore
from django.test import Client, override_settings
from django.urls import reverse

from apps.core.models import ActiveSession
from apps.core.permissions import Role
from apps.core.services import sessions
from tests.factories import make_user

HOME = reverse("core:home")


@pytest.fixture
def user():
    return make_user("stu_k7x9a2", Role.STUDENT)


def nonce_of(response):
    match = re.search(r"'nonce-([^']+)'", response["Content-Security-Policy"])
    assert match, "CSP has no nonce"
    return match.group(1)


@pytest.mark.django_db
def test_security_headers_present(client):
    response = client.get(HOME)

    csp = response["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp
    assert response["X-Frame-Options"] == "DENY"
    assert response["Referrer-Policy"] == "same-origin"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "camera=()" in response["Permissions-Policy"]
    assert response["Cross-Origin-Opener-Policy"] == "same-origin"


@pytest.mark.django_db
def test_csp_nonce_is_fresh_per_request_and_used_by_scripts(client):
    first, second = client.get(HOME), client.get(HOME)
    nonce = nonce_of(first)

    assert nonce != nonce_of(second)
    assert len(nonce) >= 16
    assert f'nonce="{nonce}"'.encode() in first.content


@pytest.mark.django_db
@override_settings(SECURE_HSTS_SECONDS=31536000, SECURE_HSTS_INCLUDE_SUBDOMAINS=True)
def test_hsts_on_https(client):
    response = client.get(HOME, secure=True)
    assert response["Strict-Transport-Security"].startswith("max-age=31536000")


@pytest.mark.django_db
def test_request_id_generated_or_propagated(client):
    generated = client.get(HOME)["X-Request-ID"]
    assert re.fullmatch(r"[0-9a-f]{32}", generated)
    assert client.get(HOME, HTTP_X_REQUEST_ID="edge-1234abcd")["X-Request-ID"] == "edge-1234abcd"
    forged = client.get(HOME, HTTP_X_REQUEST_ID="bad id\nInjected: yes")["X-Request-ID"]
    assert re.fullmatch(r"[0-9a-f]{32}", forged)


@pytest.mark.django_db
def test_no_store_only_for_authenticated(client, user):
    assert "no-store" not in client.get(HOME).get("Cache-Control", "")
    client.force_login(user)
    response = client.get(HOME)
    assert "no-store" in response["Cache-Control"]
    assert "private" in response["Cache-Control"]


@pytest.mark.django_db
def test_login_rotates_session_key(rf, user):
    request = rf.get(HOME)
    request.session = SessionStore()
    request.session["pre_login"] = True
    request.session.save()
    before = request.session.session_key

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")

    assert request.session.session_key != before
    assert request.session[sessions.LOGIN_ID_KEY]


def is_signed_in(client):
    return "_auth_user_id" in client.session


@pytest.mark.django_db
def test_single_active_session(client, user):
    client.force_login(user)
    other_device = Client()
    other_device.force_login(user)

    client.get(HOME)
    assert not is_signed_in(client)  # the older session was replaced
    other_device.get(HOME)
    assert is_signed_in(other_device)


@pytest.mark.django_db
def test_logout_forgets_active_session(client, user):
    client.force_login(user)
    assert ActiveSession.objects.filter(user=user).exists()
    client.logout()
    assert not ActiveSession.objects.filter(user=user).exists()


def age_session(client, key, seconds):
    session = client.session
    session[key] = int(time.time()) - seconds
    session.save()


@pytest.mark.django_db
@override_settings(SESSION_IDLE_TIMEOUT=600)
def test_idle_timeout(client, user):
    client.force_login(user)
    age_session(client, sessions.SEEN_AT_KEY, 599)
    client.get(HOME)
    assert is_signed_in(client)

    age_session(client, sessions.SEEN_AT_KEY, 601)
    client.get(HOME)
    assert not is_signed_in(client)


@pytest.mark.django_db
@override_settings(SESSION_ABSOLUTE_TIMEOUT=3600)
def test_absolute_timeout_even_when_active(client, user):
    client.force_login(user)
    age_session(client, sessions.AUTH_AT_KEY, 3601)
    client.get(HOME)
    assert not is_signed_in(client)


@pytest.mark.django_db
def test_session_without_binding_is_ended(client, user):
    client.force_login(user)
    session = client.session
    del session[sessions.LOGIN_ID_KEY]
    session.save()
    client.get(HOME)
    assert not is_signed_in(client)
