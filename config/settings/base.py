from datetime import timedelta
from pathlib import Path

import environ
from celery.schedules import crontab
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
    "apps.core.middleware.SavedLanguageMiddleware",
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
                "apps.accounts.context_processors.account_menu",
            ],
        },
    },
]

DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}
CACHES = {"default": env.cache("CACHE_URL", default="locmemcache://tfs")}

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:dashboard"
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
AXES_LOCKOUT_CALLABLE = "apps.accounts.views.auth.lockout_response"

# django-ratelimit: shared cache in production (Redis); fail closed if the cache is down.
RATELIMIT_USE_CACHE = "default"
RATELIMIT_FAIL_OPEN = False
RATELIMIT_IP_META_KEY = "apps.core.net.client_ip"
RATELIMIT_VIEW = "apps.core.views.ratelimited"

# One-time codes (sign-up, password reset, username recovery).
OTP_TTL_SECONDS = env.int("OTP_TTL_SECONDS", default=5 * 60)
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN = env.int("OTP_RESEND_COOLDOWN", default=60)
OTP_MAX_SENDS = 5
# After a code is verified the next step (new password) must follow within this time.
OTP_VERIFIED_TTL_SECONDS = 15 * 60
# Delivery per channel (apps.notifications.backends). SMS has no production gateway yet,
# so it stays off until a deployment provides one.
OTP_BACKENDS = {
    "email": "apps.notifications.backends.SmtpBackend",
    "sms": "apps.notifications.backends.SmsBackend",
}
OTP_SMS_ENABLED = env.bool("OTP_SMS_ENABLED", default=False)
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env(
    "DEFAULT_FROM_EMAIL", default="Teacher Feedback System <no-reply@localhost>"
)

# Authenticator apps show this as the account's issuer.
TOTP_ISSUER = "Teacher Feedback System"
# A password-checked login waits this long for its second factor.
SECOND_FACTOR_PENDING_SECONDS = 10 * 60

# Results and comment lists stay hidden below this many responses (never fewer than 3).
MIN_RESPONSES = env.int("MIN_RESPONSES", default=5)

# When teachers and heads of department may see a round's results: "after_close" (the default,
# once the round has closed) or "held" (not at all until the Admin switches back). Never earlier.
RESULTS_VISIBLE = env("RESULTS_VISIBLE", default="after_close")

# Unfinished feedback drafts are deleted this many days after the last save.
DRAFT_RETENTION_DAYS = env.int("DRAFT_RETENTION_DAYS", default=30)

# Hours before a round closes at which students with unsubmitted forms are reminded.
REMINDER_HOURS_BEFORE_CLOSE = env.list("REMINDER_HOURS_BEFORE_CLOSE", cast=int, default=[72, 24, 1])

# Whether students are told the moment a round opens.
REMINDER_ON_OPEN = env.bool("REMINDER_ON_OPEN", default=True)

# E-mail and text messages are held back from QUIET_HOURS_START until QUIET_HOURS_END
# (Asia/Dhaka hours, 0-23); in-app notices are never held. Equal hours switch it off.
QUIET_HOURS_START = env.int("QUIET_HOURS_START", default=22)
QUIET_HOURS_END = env.int("QUIET_HOURS_END", default=7)

# Delivery per channel for notifications (apps.notifications.senders); SMS needs a gateway.
NOTIFICATION_SENDERS = {
    "email": "apps.notifications.senders.EmailSender",
    "sms": "apps.notifications.senders.SmsSender",
}
NOTIFICATION_SMS_ENABLED = env.bool("NOTIFICATION_SMS_ENABLED", default=False)
# Links in e-mails and texts start with this address.
SITE_URL = env("SITE_URL", default="http://localhost:8000").rstrip("/")

# Scheduled jobs; a Celery beat process runs them (or ``manage.py send_notifications`` by hand).
CELERY_BEAT_SCHEDULE = {
    "round-reminders": {
        "task": "notifications.send_round_reminders",
        "schedule": crontab(minute="*/10"),
    },
    "hod-reminders": {
        "task": "notifications.process_reminder_requests",
        "schedule": crontab(minute="*/5"),
    },
    "results-notices": {
        "task": "notifications.announce_results",
        "schedule": crontab(minute="*/15"),
    },
}

# A course average below this raises an alert card on the head of department's overview.
LOW_RATING_THRESHOLD = env.float("LOW_RATING_THRESHOLD", default=3.5)

# Whether a student sees their own student ID on their pages (off: the ID is never shown to them).
SHOW_OWN_ID_TO_STUDENT = env.bool("SHOW_OWN_ID_TO_STUDENT", default=False)

# What the comment filter does with abusive words: "remove" them or "mask" them with asterisks.
PROFANITY_ACTION = env("PROFANITY_ACTION", default="remove")
# Optional AI check of comments (only the comment text is sent, after personal details are removed).
# A failure or timeout falls back to the local word lists, so a submission never waits on it.
FILTER_AI_ENABLED = env.bool("FILTER_AI_ENABLED", default=False)
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
FILTER_AI_MODEL = env("FILTER_AI_MODEL", default="claude-haiku-5-5")
FILTER_AI_TIMEOUT = env.float("FILTER_AI_TIMEOUT", default=3.0)

LOGGING = build_logging_config(
    json_logs=env.bool("LOG_JSON", default=False), level=env("LOG_LEVEL", default="INFO")
)
