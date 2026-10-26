"""Outgoing channels for notifications (selected per channel by ``settings.NOTIFICATION_SENDERS``).

A sender delivers one finished message and raises if it cannot. Callers log the outcome
without the text or the destination.
"""

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import send_mail
from django.utils.module_loading import import_string

EMAIL = "email"
SMS = "sms"
IN_APP = "in_app"
EXTERNAL_CHANNELS = (EMAIL, SMS)


@dataclass(frozen=True)
class Message:
    channel: str
    destination: str
    subject: str
    body: str


class Sender(ABC):
    @abstractmethod
    def send(self, message: Message) -> None:
        """Deliver ``message`` or raise."""


class EmailSender(Sender):
    """E-mail through the SMTP server in ``EMAIL_*`` settings."""

    def send(self, message: Message) -> None:
        if message.channel != EMAIL:
            raise ImproperlyConfigured("EmailSender delivers e-mail only.")
        send_mail(message.subject, message.body, None, [message.destination])


class ConsoleSender(Sender):
    """Development only: print the message to the server console."""

    def send(self, message: Message) -> None:
        if not settings.DEBUG:
            raise ImproperlyConfigured("ConsoleSender prints messages and is for DEBUG only.")
        sys.stdout.write(f"[{message.channel}] {message.subject}\n{message.body}\n")


class SmsSender(Sender):
    """Interface for a text-message gateway.

    No gateway ships with the project: a deployment subclasses this, implements ``send`` and
    points ``NOTIFICATION_SENDERS["sms"]`` at it, then switches ``NOTIFICATION_SMS_ENABLED`` on.
    """

    def send(self, message: Message) -> None:
        raise NotImplementedError("Configure an SMS gateway in NOTIFICATION_SENDERS['sms'].")


def get_sender(channel: str) -> Sender:
    try:
        path = settings.NOTIFICATION_SENDERS[channel]
    except KeyError:
        raise ImproperlyConfigured(f"No notification sender for channel {channel!r}.") from None
    return import_string(path)()
