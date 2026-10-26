from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver"]

# Django admin is a development convenience only; it is never installed in production.
INSTALLED_APPS = ["django.contrib.admin", *INSTALLED_APPS]  # noqa: F405
ACCESS_POLICY_EXEMPT_NAMESPACES = ["admin"]  # admin guards itself with is_staff
# Uploaded avatars and photos are served by the dev server only (a proxy serves them in production).
ACCESS_POLICY_EXEMPT_VIEWS = [*ACCESS_POLICY_EXEMPT_VIEWS, "media"]  # noqa: F405

# Codes are printed to the server console instead of being sent.
OTP_BACKENDS = {
    "email": "apps.notifications.backends.ConsoleBackend",
    "sms": "apps.notifications.backends.ConsoleBackend",
}
OTP_SMS_ENABLED = True

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Local runs may use the in-process cache; production requires Redis (see prod.py).
SILENCED_SYSTEM_CHECKS = ["django_ratelimit.E003", "django_ratelimit.W001"]
