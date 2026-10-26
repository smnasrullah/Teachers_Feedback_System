from smtplib import SMTPException

from celery import shared_task
from django.utils import translation

from apps.core.encryption import decrypt
from apps.notifications.otp import OtpMessage, get_backend


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
