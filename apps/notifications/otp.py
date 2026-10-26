"""One-time code messages and their hand-off to the delivery task.

The plaintext code travels to the worker only as a Fernet token, so it never sits in the
broker queue readable. Nothing here logs a code or a destination.
"""

from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import translation
from django.utils.module_loading import import_string
from django.utils.translation import gettext as _

from apps.core.encryption import encrypt

EMAIL = "email"
SMS = "sms"
CHANNELS = (EMAIL, SMS)


@dataclass(frozen=True)
class OtpMessage:
    channel: str
    destination: str
    purpose: str
    code: str
    ttl_minutes: int

    @property
    def subject(self) -> str:
        return {
            "signup": _("Your sign-up code"),
            "password_reset": _("Your password reset code"),
            "username_recovery": _("Your username recovery code"),
        }.get(self.purpose, _("Your verification code"))

    @property
    def body(self) -> str:
        return _(
            "Your Teacher Feedback System code is %(code)s. It expires in %(minutes)d minutes. "
            "If you did not ask for it, ignore this message and tell nobody the code."
        ) % {"code": self.code, "minutes": self.ttl_minutes}


def get_backend(channel: str):
    try:
        path = settings.OTP_BACKENDS[channel]
    except KeyError:
        raise ImproperlyConfigured(f"No one-time code backend for channel {channel!r}.") from None
    return import_string(path)()


def dispatch(
    channel: str, destination: str | None, code: str, purpose: str, *, language: str | None = None
) -> None:
    """Queue delivery. ``destination=None`` queues a no-op so unknown accounts cost the same."""
    from apps.notifications.tasks import send_otp

    send_otp.delay(
        channel,
        encrypt(destination) if destination else "",
        encrypt(code),
        purpose,
        language or translation.get_language() or settings.LANGUAGE_CODE,
        settings.OTP_TTL_SECONDS // 60,
    )
