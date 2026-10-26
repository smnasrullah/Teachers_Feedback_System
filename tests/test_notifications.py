import pytest
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.utils import translation

from apps.notifications import otp as delivery
from apps.notifications import tasks
from apps.notifications.backends import ConsoleBackend, SmsBackend, SmtpBackend
from apps.notifications.otp import OtpMessage


@pytest.fixture(autouse=True)
def english():
    """The site default is Bangla; these tests assert the English wording."""
    with translation.override("en"):
        yield


MESSAGE = OtpMessage(
    channel="email",
    destination="ana@example.com",
    purpose="password_reset",
    code="123456",
    ttl_minutes=5,
)


def test_message_text_names_the_code_and_lifetime():
    assert "123456" in MESSAGE.body
    assert "5 minutes" in MESSAGE.body
    assert MESSAGE.subject == "Your password reset code"


def test_smtp_backend_sends_an_email():
    SmtpBackend().send(MESSAGE)
    assert [m.to for m in mail.outbox] == [["ana@example.com"]]
    assert "123456" in mail.outbox[0].body


def test_smtp_backend_refuses_other_channels():
    with pytest.raises(ImproperlyConfigured):
        SmtpBackend().send(OtpMessage("sms", "+8801700000000", "signup", "123456", 5))


def test_console_backend_prints_in_debug_only(capsys, settings):
    settings.DEBUG = True
    ConsoleBackend().send(MESSAGE)
    assert "123456" in capsys.readouterr().out
    settings.DEBUG = False
    with pytest.raises(ImproperlyConfigured):
        ConsoleBackend().send(MESSAGE)
    assert "123456" not in capsys.readouterr().out


def test_sms_backend_is_an_interface_without_a_gateway():
    with pytest.raises(NotImplementedError):
        SmsBackend().send(OtpMessage("sms", "+8801700000000", "signup", "123456", 5))


def test_backends_are_chosen_per_channel(settings):
    settings.OTP_BACKENDS = {"email": "apps.notifications.backends.SmtpBackend"}
    assert isinstance(delivery.get_backend("email"), SmtpBackend)
    with pytest.raises(ImproperlyConfigured):
        delivery.get_backend("sms")


def test_the_code_travels_to_the_worker_encrypted(monkeypatch):
    queued = []
    monkeypatch.setattr(tasks.send_otp, "delay", lambda *args: queued.append(args))
    delivery.dispatch("email", "ana@example.com", "654321", "signup", language="en")
    assert queued
    assert "654321" not in repr(queued)
    assert "ana@example.com" not in repr(queued)


def test_a_decoy_queues_a_no_op(monkeypatch, sent):
    queued = []
    monkeypatch.setattr(tasks.send_otp, "delay", lambda *args: queued.append(args))
    delivery.dispatch("email", None, "654321", "signup", language="en")
    assert queued[0][1] == ""  # no destination
    tasks.send_otp(*queued[0])
    assert sent == []
    assert mail.outbox == []


def test_task_delivers_in_the_requested_language(sent):
    delivery.dispatch("email", "ana@example.com", "654321", "signup", language="bn")
    assert sent[-1].code == "654321"
    assert sent[-1].destination == "ana@example.com"
