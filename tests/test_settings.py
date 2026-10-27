import pytest
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from apps.core.net import UNKNOWN_IP, client_ip
from apps.core.permissions import Role
from tests.factories import make_user
from tests.prod_env import run_manage, shell


def test_argon2id_is_the_primary_hasher():
    assert make_password("Long-enough-pass-1").startswith("argon2$argon2id$")


@pytest.mark.parametrize("password", ["short1!", "password123", "4815162342108", "stu_k7x9a2-x"])
def test_password_validators_reject_weak_passwords(password, django_user_model):
    user = django_user_model(username="stu_k7x9a2")
    with pytest.raises(ValidationError):
        validate_password(password, user)


def test_cookie_and_session_flags():
    assert settings.SESSION_COOKIE_HTTPONLY
    assert settings.CSRF_COOKIE_HTTPONLY
    assert settings.SESSION_COOKIE_SAMESITE == "Lax"
    assert settings.SESSION_EXPIRE_AT_BROWSER_CLOSE


@pytest.mark.django_db
def test_axes_locks_out_after_repeated_failures(rf):
    make_user("stu_lock01", Role.STUDENT)

    def attempt(password):
        request = rf.post("/login/", REMOTE_ADDR="198.51.100.4")
        return authenticate(request, username="stu_lock01", password=password)

    for _ in range(settings.AXES_FAILURE_LIMIT):
        assert attempt("wrong-password") is None
    assert attempt("Long-enough-pass-1") is None  # locked even with the right password


@pytest.mark.parametrize(
    ("proxies", "meta", "expected"),
    [
        (0, {"REMOTE_ADDR": "10.0.0.1", "HTTP_X_FORWARDED_FOR": "1.2.3.4"}, "10.0.0.1"),
        (1, {"REMOTE_ADDR": "10.0.0.1", "HTTP_X_FORWARDED_FOR": "6.6.6.6, 1.2.3.4"}, "1.2.3.4"),
        (2, {"REMOTE_ADDR": "10.0.0.1", "HTTP_X_FORWARDED_FOR": "1.2.3.4, 10.0.0.9"}, "1.2.3.4"),
        (1, {"REMOTE_ADDR": "10.0.0.1", "HTTP_X_FORWARDED_FOR": "not-an-ip"}, "10.0.0.1"),
        (1, {"REMOTE_ADDR": "10.0.0.1"}, "10.0.0.1"),
        (0, {"REMOTE_ADDR": ""}, UNKNOWN_IP),
    ],
)
def test_client_ip_trusts_only_configured_proxies(rf, settings, proxies, meta, expected):
    settings.TRUSTED_PROXY_COUNT = proxies
    request = rf.get("/")
    request.META.update(meta)
    assert client_ip(request) == expected


def test_prod_settings_pass_deploy_checks():
    result = run_manage("check", "--deploy", "--fail-level", "WARNING")
    assert result.returncode == 0, result.stdout + result.stderr


def test_django_admin_not_installed_in_prod():
    code = "from django.apps import apps; print(apps.is_installed('django.contrib.admin'))"
    assert shell(code) == "False"
