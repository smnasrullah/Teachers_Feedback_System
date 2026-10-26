"""Delivery backends for one-time codes (selected per channel by ``settings.OTP_BACKENDS``)."""

import sys
from abc import ABC, abstractmethod

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import send_mail

from apps.notifications.otp import EMAIL, OtpMessage


class OtpBackend(ABC):
    @abstractmethod
    def send(self, message: OtpMessage) -> None:
        """Deliver ``message`` or raise; the caller never sees the destination again."""


class ConsoleBackend(OtpBackend):
    """Development only: print the code to the server console."""

    def send(self, message: OtpMessage) -> None:
        if not settings.DEBUG:
            raise ImproperlyConfigured("ConsoleBackend prints codes and is for DEBUG only.")
        sys.stdout.write(
            f"[one-time code] {message.channel} -> {message.destination}: "
            f"{message.subject}\n{message.body}\n"
        )


class SmtpBackend(OtpBackend):
    """E-mail through the SMTP server in ``EMAIL_*`` settings."""

    def send(self, message: OtpMessage) -> None:
        if message.channel != EMAIL:
            raise ImproperlyConfigured("SmtpBackend delivers e-mail only.")
        send_mail(message.subject, message.body, None, [message.destination])


class SmsBackend(OtpBackend):
    """Interface for a text-message gateway.

    No gateway ships with the project: a deployment subclasses this, implements ``send`` and
    points ``OTP_BACKENDS["sms"]`` at it. Until then ``OTP_SMS_ENABLED`` stays off and the
    forms only offer e-mail.
    """

    def send(self, message: OtpMessage) -> None:
        raise NotImplementedError("Configure an SMS gateway backend in OTP_BACKENDS['sms'].")
