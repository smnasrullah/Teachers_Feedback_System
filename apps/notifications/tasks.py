from smtplib import SMTPException

from celery import shared_task
from django.utils import translation

from apps.core.encryption import decrypt
from apps.notifications.otp import OtpMessage, get_backend
from apps.notifications.services import schedule


@shared_task(
    name="notifications.send_otp",
    ignore_result=True,
    autoretry_for=(SMTPException, OSError),
    retry_backoff=True,
    max_retries=3,
)
def send_otp(
    channel: str,
    destination_token: str,
    code_token: str,
    purpose: str,
    language: str,
    ttl_minutes: int,
) -> None:
    """Deliver one code. An empty destination is a decoy for an unknown account: do nothing."""
    if not destination_token:
        return
    message = OtpMessage(
        channel=channel,
        destination=decrypt(destination_token),
        purpose=purpose,
        code=decrypt(code_token),
        ttl_minutes=ttl_minutes,
    )
    with translation.override(language):
        get_backend(channel).send(message)


@shared_task(name="notifications.send_round_reminders", ignore_result=True)
def send_round_reminders() -> None:
    schedule.send_round_reminders()


@shared_task(name="notifications.process_reminder_requests", ignore_result=True)
def process_reminder_requests() -> None:
    schedule.process_reminder_requests()


@shared_task(name="notifications.announce_results", ignore_result=True)
def announce_results() -> None:
    schedule.announce_results()
