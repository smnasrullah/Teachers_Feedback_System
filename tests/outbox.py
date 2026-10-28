"""In-memory notification delivery for tests (selected by ``config.settings.test``)."""

from apps.notifications.senders import Message, Sender

texts: list[Message] = []


class OutboxSender(Sender):
    def send(self, message: Message) -> None:
        texts.append(message)
