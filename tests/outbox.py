"""In-memory one-time code delivery for tests (selected by ``config.settings.test``)."""

from apps.notifications.backends import OtpBackend
from apps.notifications.otp import OtpMessage

sent: list[OtpMessage] = []


class OutboxBackend(OtpBackend):
    def send(self, message: OtpMessage) -> None:
        sent.append(message)
