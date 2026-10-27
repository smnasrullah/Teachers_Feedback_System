import os

# Fixed, test-only values (never used outside the test run); real env vars still win.
os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("FIELD_ENCRYPTION_KEYS", "dGVzdC1maWVsZC1lbmNyeXB0aW9uLWtleS0wMDAwMDA=")
os.environ.setdefault("BLIND_INDEX_KEY", "test-blind-index-key-0123456789abcdef")

from .dev import *  # noqa: F403

# Test-only models (encrypted fields) live in tests/testapp.
INSTALLED_APPS = [*INSTALLED_APPS, "tests.testapp"]  # noqa: F405

# Texts land in memory too; e-mail uses Django's in-memory mailbox.
NOTIFICATION_SENDERS = {
    "email": "apps.notifications.senders.EmailSender",
    "sms": "tests.outbox.OutboxSender",
}
NOTIFICATION_SMS_ENABLED = True
