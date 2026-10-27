"""Run ``manage.py`` in a child process under the real production settings.

The child gets a strong throwaway environment and never reads the developer's .env, so results
do not depend on the machine the tests run on. Nothing connects to the database or Redis.
"""

import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from django.conf import settings

BASE_DIR = Path(settings.BASE_DIR)
EXAMPLE_FILES = (".env.example", ".env.production.example")
_VARIABLE = re.compile(r"^#?\s*([A-Z][A-Z0-9_]+)=", re.MULTILINE)


def documented_variables(*files: str) -> set[str]:
    """Every NAME= line (set or commented out) of the example env files (default: both)."""
    names: set[str] = set()
    for name in files or EXAMPLE_FILES:
        names.update(_VARIABLE.findall((BASE_DIR / name).read_text(encoding="utf-8")))
    return names


def strong_env() -> dict[str, str]:
    return {
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(64),
        "FIELD_ENCRYPTION_KEYS": Fernet.generate_key().decode(),
        "BLIND_INDEX_KEY": secrets.token_urlsafe(48),
        "DJANGO_ALLOWED_HOSTS": "feedback.example.edu",
        "DJANGO_CSRF_TRUSTED_ORIGINS": "https://feedback.example.edu",
        "SITE_URL": "https://feedback.example.edu",
        # Nothing listens there: a stray connection attempt fails fast instead of hanging.
        "DATABASE_URL": f"postgres://tfs:{secrets.token_hex(24)}@127.0.0.1:9/tfs?connect_timeout=2",
        "CACHE_URL": "redis://127.0.0.1:6379/2",
        "CELERY_BROKER_URL": "redis://127.0.0.1:6379/0",
        "CELERY_RESULT_BACKEND": "redis://127.0.0.1:6379/1",
    }


def run_manage(
    *args: str,
    overrides: dict[str, str | None] | None = None,
    settings_module: str = "config.settings.prod",
) -> subprocess.CompletedProcess:
    """``overrides`` replace variables of the strong env; ``None`` removes one."""
    clean = {
        key: value
        for key, value in os.environ.items()
        if key not in documented_variables() and key != "DEMO_PASSWORD"
    }
    env = {
        **clean,
        **strong_env(),
        "DJANGO_SETTINGS_MODULE": settings_module,
        "DJANGO_READ_ENV_FILE": "false",
    }
    for key, value in (overrides or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "manage.py", *args],
        cwd=BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )


def shell(code: str, **kwargs) -> str:
    """Run ``code`` in ``manage.py shell`` and return its last output line."""
    result = run_manage("shell", "-c", code, **kwargs)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()[-1]
