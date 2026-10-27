"""Production readiness: startup refusals, production flags, dev features off, deploy kit files."""

import json
import re
import secrets

import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured
from django.test import Client
from django.urls import reverse

from apps.core.services import health
from config.settings.hardening import require_production_settings
from tests.prod_env import BASE_DIR, documented_variables, run_manage, shell, strong_env

SECRET_NAMES = ("DJANGO_SECRET_KEY", "FIELD_ENCRYPTION_KEYS", "BLIND_INDEX_KEY")


def valid_kwargs(**changes):
    env = strong_env()
    kwargs = {
        "secret_key": env["DJANGO_SECRET_KEY"],
        "fernet_keys": [env["FIELD_ENCRYPTION_KEYS"]],
        "blind_index_key": env["BLIND_INDEX_KEY"],
        "database_url": env["DATABASE_URL"],
        "redis_urls": {"CACHE_URL": env["CACHE_URL"]},
        "allowed_hosts": ["feedback.example.edu"],
        "csrf_origins": ["https://feedback.example.edu"],
        "site_url": "https://feedback.example.edu",
    }
    return {**kwargs, **changes}


def test_strong_settings_are_accepted():
    require_production_settings(**valid_kwargs())


@pytest.mark.parametrize(
    ("changes", "named"),
    [
        ({"secret_key": "change-me"}, "DJANGO_SECRET_KEY"),
        ({"secret_key": "a" * 80}, "DJANGO_SECRET_KEY"),
        ({"secret_key": "django-insecure-" + secrets.token_urlsafe(48)}, "DJANGO_SECRET_KEY"),
        ({"fernet_keys": ["change-me"]}, "FIELD_ENCRYPTION_KEYS"),
        ({"fernet_keys": []}, "FIELD_ENCRYPTION_KEYS"),
        # A valid Fernet encoding of a typed, patterned key (the test settings' key).
        (
            {"fernet_keys": ["dGVzdC1maWVsZC1lbmNyeXB0aW9uLWtleS0wMDAwMDA="]},
            "FIELD_ENCRYPTION_KEYS",
        ),
        ({"blind_index_key": "change-me"}, "BLIND_INDEX_KEY"),
        ({"blind_index_key": "short-key"}, "BLIND_INDEX_KEY"),
        ({"database_url": "sqlite:///db.sqlite3"}, "DATABASE_URL"),
        ({"database_url": "postgres://tfs:change-me@db:5432/tfs"}, "DATABASE_URL"),
        ({"redis_urls": {"CACHE_URL": "locmemcache://tfs"}}, "CACHE_URL"),
        ({"allowed_hosts": []}, "DJANGO_ALLOWED_HOSTS"),
        ({"allowed_hosts": ["*"]}, "DJANGO_ALLOWED_HOSTS"),
        ({"csrf_origins": ["http://feedback.example.edu"]}, "DJANGO_CSRF_TRUSTED_ORIGINS"),
        ({"site_url": "http://feedback.example.edu"}, "SITE_URL"),
    ],
)
def test_weak_or_unsafe_settings_are_refused(changes, named):
    with pytest.raises(ImproperlyConfigured, match=named):
        require_production_settings(**valid_kwargs(**changes))


def test_reused_keys_are_refused():
    kwargs = valid_kwargs()
    with pytest.raises(ImproperlyConfigured, match="BLIND_INDEX_KEY must differ"):
        require_production_settings(**{**kwargs, "blind_index_key": kwargs["secret_key"]})
    key = Fernet.generate_key().decode()
    with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY must differ"):
        require_production_settings(**{**kwargs, "secret_key": key, "fernet_keys": [key]})


def test_the_refusal_never_contains_the_secret_values():
    weak = {"secret_key": "short-but-secret-value", "blind_index_key": "tiny-secret"}
    with pytest.raises(ImproperlyConfigured) as caught:
        require_production_settings(**valid_kwargs(**weak))
    assert "short-but-secret-value" not in str(caught.value)
    assert "tiny-secret" not in str(caught.value)


@pytest.mark.parametrize(
    "missing",
    [
        *SECRET_NAMES,
        "DJANGO_ALLOWED_HOSTS",
        "DATABASE_URL",
        "CACHE_URL",
        "CELERY_BROKER_URL",
        "CELERY_RESULT_BACKEND",
        "SITE_URL",
    ],
)
def test_a_missing_variable_stops_startup(missing):
    result = run_manage("check", overrides={missing: None})
    assert result.returncode != 0
    assert missing in result.stderr


def test_a_weak_key_stops_startup_without_printing_it():
    result = run_manage("check", overrides={"DJANGO_SECRET_KEY": "change-me-please-1234567890"})
    assert result.returncode != 0
    assert "Production settings refused" in result.stderr
    assert "change-me-please-1234567890" not in result.stderr + result.stdout


def test_the_unedited_production_example_is_refused():
    values = dict(
        re.findall(
            r"^([A-Z][A-Z0-9_]+)=(.*)$",
            (BASE_DIR / ".env.production.example").read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    )
    overrides = {name: values[name] for name in SECRET_NAMES}
    result = run_manage("check", overrides=overrides)
    assert result.returncode != 0
    for name in SECRET_NAMES:
        assert name in result.stderr


def test_production_flags_are_set():
    names = [
        "DEBUG",
        "SECURE_SSL_REDIRECT",
        "SECURE_PROXY_SSL_HEADER",
        "SECURE_HSTS_SECONDS",
        "SECURE_HSTS_INCLUDE_SUBDOMAINS",
        "SECURE_HSTS_PRELOAD",
        "SESSION_COOKIE_SECURE",
        "SESSION_COOKIE_HTTPONLY",
        "SESSION_COOKIE_SAMESITE",
        "CSRF_COOKIE_SECURE",
        "CSRF_COOKIE_HTTPONLY",
        "CSRF_COOKIE_SAMESITE",
        "X_FRAME_OPTIONS",
        "SECURE_REFERRER_POLICY",
        "SECURE_CONTENT_TYPE_NOSNIFF",
        "DEMO_SKIP_SECOND_FACTOR",
        "DEMO_PASSWORD",
        "TRUSTED_PROXY_COUNT",
    ]
    code = (
        "import json; from django.conf import settings as s; "
        f"print(json.dumps({{n: getattr(s, n) for n in {names!r}}}))"
    )
    flags = json.loads(shell(code, overrides={"DEMO_PASSWORD": "Demo-Pass-123!"}))
    assert flags == {
        "DEBUG": False,
        "SECURE_SSL_REDIRECT": True,
        "SECURE_PROXY_SSL_HEADER": ["HTTP_X_FORWARDED_PROTO", "https"],
        "SECURE_HSTS_SECONDS": 31536000,
        "SECURE_HSTS_INCLUDE_SUBDOMAINS": True,
        "SECURE_HSTS_PRELOAD": False,
        "SESSION_COOKIE_SECURE": True,
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "CSRF_COOKIE_SECURE": True,
        "CSRF_COOKIE_HTTPONLY": True,
        "CSRF_COOKIE_SAMESITE": "Lax",
        "X_FRAME_OPTIONS": "DENY",
        "SECURE_REFERRER_POLICY": "same-origin",
        "SECURE_CONTENT_TYPE_NOSNIFF": True,
        "DEMO_SKIP_SECOND_FACTOR": False,
        "DEMO_PASSWORD": "",
        "TRUSTED_PROXY_COUNT": 1,
    }


def test_debug_cannot_be_switched_on_from_the_environment():
    code = "from django.conf import settings; print(settings.DEBUG)"
    assert shell(code, overrides={"DJANGO_DEBUG": "true"}) == "False"


def test_the_admin_path_is_not_routed_in_production():
    code = (
        "from django.urls import Resolver404, resolve\n"
        "try:\n    resolve('/admin/')\n    print('routed')\n"
        "except Resolver404:\n    print('absent')"
    )
    assert shell(code) == "absent"


@pytest.mark.parametrize(
    "command", [["seed_demo", "--password", "Demo-Pass-123!"], ["totp_code", "x"]]
)
def test_dev_commands_refuse_to_run_in_production(command):
    result = run_manage(*command)
    assert result.returncode != 0
    assert "config.settings.dev" in result.stderr


def test_the_login_demo_box_is_closed_in_production():
    code = "from apps.accounts.services.login import demo_box; print(demo_box())"
    assert shell(code, overrides={"DEMO_PASSWORD": "Demo-Pass-123!"}) == "None"


def test_the_demo_shortcut_fails_the_system_check_in_production():
    result = run_manage("check", settings_module="tests.prod_demo_settings")
    assert result.returncode != 0
    assert "core.E004" in result.stderr


@pytest.mark.django_db
def test_healthz_over_https_reveals_nothing(settings):
    settings.SECURE_SSL_REDIRECT = True
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    response = Client().get(reverse("core:healthz"), HTTP_X_FORWARDED_PROTO="https")
    assert response.status_code == 200
    assert response.content == b'{"status": "ok"}'
    assert "Set-Cookie" not in response
    assert "no-cache" in response["Cache-Control"]


def test_healthz_failure_reveals_no_detail(monkeypatch):
    class UnreachableDatabase:
        def cursor(self):
            raise RuntimeError("could not connect to server at db:5432 as user tfs")

    monkeypatch.setattr(health, "connection", UnreachableDatabase())
    response = Client().get(reverse("core:healthz"))
    assert response.status_code == 503
    assert response.content == b'{"status": "error"}'


def test_every_setting_the_app_reads_is_documented_for_production():
    pattern = re.compile(r"env(?:\.\w+)?\(\s*\"([A-Z][A-Z0-9_]+)\"")
    read = set()
    for name in ("base.py", "prod.py"):
        read.update(pattern.findall((BASE_DIR / "config" / "settings" / name).read_text("utf-8")))
    assert read - documented_variables(".env.production.example") == set()


def test_real_env_files_and_data_are_kept_out_of_git_and_the_image():
    gitignore = (BASE_DIR / ".gitignore").read_text(encoding="utf-8").splitlines()
    dockerignore = (BASE_DIR / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for pattern in (".env", ".env.*", "db.sqlite3", "/media/", "*.dump"):
        assert pattern in gitignore
    for pattern in (".env", ".env.*", "*.sqlite3", "media", "*.dump", ".git"):
        assert pattern in dockerignore
    assert "!.env.production.example" in gitignore
