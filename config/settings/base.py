from datetime import timedelta
from pathlib import Path

import environ
from django.utils.translation import gettext_lazy as _

from apps.core.logging import build_logging_config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

# Field encryption (Fernet). First key encrypts, all keys decrypt; see rotate_encryption_keys.
FIELD_ENCRYPTION_KEYS = env.list("FIELD_ENCRYPTION_KEYS")
# HMAC key for blind indexes; must differ from the encryption keys and SECRET_KEY.
BLIND_INDEX_KEY = env("BLIND_INDEX_KEY")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_tailwind_cli",
    "axes",
    "django_ratelimit",
    "apps.core",
    "apps.accounts",
    "apps.academics",
    "apps.enrollment",
    "apps.feedback",
    "apps.analytics",
    "apps.reports",
    "apps.notifications",
    "apps.auditlog",
]

MIDDLEWARE = [
    "apps.core.middleware.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "apps.core.middleware.SessionSecurityMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
    "apps.core.middleware.AccessPolicyMiddleware",
    "django_ratelimit.middleware.RatelimitMiddleware",
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.csp_nonce",
            ],
        },
    },
]

DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}
CACHES = {"default": env.cache("CACHE_URL", default="locmemcache://tfs")}

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
# Argon2id first; PBKDF2 stays only so any legacy hash still verifies and is upgraded on login.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

LANGUAGE_CODE = "bn"
LANGUAGES = [("bn", _("Bangla")), ("en", _("English"))]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Asia/Dhaka"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
# User uploads (avatars, teacher photos). Always re-encoded by apps.core.uploads first.
MEDIA_URL = "media/"
MEDIA_ROOT = env.path("MEDIA_ROOT", default=str(BASE_DIR / "media"))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

TAILWIND_CLI_SRC_CSS = "frontend/input.css"
TAILWIND_CLI_DIST_CSS = "css/tailwind.css"

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/1")
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
# Keep our logging config (and its scrubber) in workers.
CELERY_WORKER_HIJACK_ROOT_LOGGER = False

# Sessions: Django rotates the key on login; SessionSecurityMiddleware enforces the rest.
SESSION_IDLE_TIMEOUT = env.int("SESSION_IDLE_TIMEOUT", default=30 * 60)
SESSION_ABSOLUTE_TIMEOUT = env.int("SESSION_ABSOLUTE_TIMEOUT", default=12 * 60 * 60)
SESSION_COOKIE_AGE = SESSION_ABSOLUTE_TIMEOUT
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
# HTMX reads the token from a <meta> tag, so the cookie need not be readable by JS.
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

# Deny by default (apps.core.permissions). Third-party URLs that guard themselves:
ACCESS_POLICY_EXEMPT_VIEWS = ["set_language"]  # POST-only, CSRF-protected, no data
ACCESS_POLICY_EXEMPT_NAMESPACES: list[str] = []

# Reverse proxies in front of the app that append to X-Forwarded-For (0 = direct).
TRUSTED_PROXY_COUNT = env.int("TRUSTED_PROXY_COUNT", default=0)

# django-axes: lock a username per client address (a shared campus NAT must not lock
# out everyone), reset on success. Per-IP volume is capped by django-ratelimit.
AXES_FAILURE_LIMIT = env.int("AXES_FAILURE_LIMIT", default=5)
AXES_COOLOFF_TIME = timedelta(minutes=env.int("AXES_COOLOFF_MINUTES", default=15))
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_CLIENT_IP_CALLABLE = "apps.core.net.client_ip"
AXES_SENSITIVE_PARAMETERS = ["password", "otp", "token", "code"]

# django-ratelimit: shared cache in production (Redis); fail closed if the cache is down.
RATELIMIT_USE_CACHE = "default"
RATELIMIT_FAIL_OPEN = False
RATELIMIT_IP_META_KEY = "apps.core.net.client_ip"
RATELIMIT_VIEW = "apps.core.views.ratelimited"

LOGGING = build_logging_config(
    json_logs=env.bool("LOG_JSON", default=False), level=env("LOG_LEVEL", default="INFO")
)
