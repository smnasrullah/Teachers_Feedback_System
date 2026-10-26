"""One-time codes: 6 digits, stored as a keyed hash, expiring, attempt- and resend-limited.

A challenge for an account that does not exist (a *decoy*) is created, verified and resent
exactly like a real one but delivers nothing, so callers cannot tell the two apart.
"""

import hmac
import math
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import OneTimeCode, User
from apps.accounts.services.identifiers import BANGLA_DIGITS
from apps.core.encryption import blind_index
from apps.notifications import otp as delivery

HASH_PURPOSE = "auth.otp"
CODE_LENGTH = 6


class VerifyStatus(StrEnum):
    OK = "ok"
    WRONG = "wrong"
    EXPIRED = "expired"
    LOCKED = "locked"


class ResendError(Exception):
    """Resending is refused; ``wait`` is the seconds left when a cooldown caused it."""

    def __init__(self, wait: int = 0):
        super().__init__(wait)
        self.wait = wait


@dataclass(frozen=True)
class Contact:
    channel: str
    destination: str


def _hash(challenge_id: uuid.UUID | str, code: str) -> str:
    return blind_index(f"{challenge_id}:{code}", HASH_PURPOSE)


def _new_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(CODE_LENGTH))


def normalize_code(value: str) -> str:
    """Digits only; Bangla digits and separators are accepted."""
    return "".join(ch for ch in str(value).translate(BANGLA_DIGITS) if ch.isdigit())


def sms_enabled() -> bool:
    return settings.OTP_SMS_ENABLED


def contact_for(user: User | None) -> Contact | None:
    """Where a recovery code for ``user`` goes: e-mail first, then phone when SMS is on."""
    if user is None:
        return None
    if user.contact_email:
        return Contact(delivery.EMAIL, user.contact_email)
    if user.contact_phone and sms_enabled():
        return Contact(delivery.SMS, user.contact_phone)
    return None


def _send(challenge: OneTimeCode, code: str, destination: str | None) -> None:
    delivery.dispatch(challenge.channel, destination, code, challenge.purpose)


def _stamp(challenge: OneTimeCode, code: str) -> None:
    now = timezone.now()
    challenge.code_hash = _hash(challenge.pk, code)
    challenge.sent_at = now
    challenge.expires_at = now + timedelta(seconds=settings.OTP_TTL_SECONDS)
    challenge.attempts = 0


@transaction.atomic
def start(
    purpose: str,
    *,
    channel: str,
    destination: str | None,
    user: User | None = None,
    registry=None,
    keep_destination: bool = False,
) -> OneTimeCode:
    """Create a challenge and deliver its code to ``destination`` (``None`` = decoy)."""
    code = _new_code()
    challenge = OneTimeCode(
        purpose=purpose,
        channel=channel,
        user=user,
        registry=registry,
        destination=destination if keep_destination else None,
    )
    _stamp(challenge, code)
    challenge.save()
    _send(challenge, code, destination)
    return challenge


def start_recovery(purpose: str, user: User | None) -> OneTimeCode:
    """Challenge for a password or username recovery; decoy when there is nobody to send to."""
    contact = contact_for(user)
    if contact is None:
        return start(purpose, channel=delivery.EMAIL, destination=None)
    return start(purpose, channel=contact.channel, destination=contact.destination, user=user)


def get_active(challenge_id, purpose: str) -> OneTimeCode | None:
    """The challenge a session points at, or ``None`` (unknown id, wrong purpose, consumed)."""
    try:
        return OneTimeCode.objects.get(pk=challenge_id, purpose=purpose, consumed_at__isnull=True)
    except (OneTimeCode.DoesNotExist, ValidationError, ValueError, TypeError):
        return None


def seconds_until_resend(challenge: OneTimeCode) -> int:
    ready = challenge.sent_at + timedelta(seconds=settings.OTP_RESEND_COOLDOWN)
    remaining = (ready - timezone.now()).total_seconds()
    return math.ceil(remaining) if remaining > 0 else 0


@transaction.atomic
def resend(challenge: OneTimeCode, destination: str | None) -> None:
    """Issue a fresh code on the same challenge, subject to the cooldown and a send cap."""
    challenge = OneTimeCode.objects.select_for_update().get(pk=challenge.pk)
    if challenge.consumed_at or challenge.verified_at:
        raise ResendError
    wait = seconds_until_resend(challenge)
    if wait:
        raise ResendError(wait)
    if challenge.send_count >= settings.OTP_MAX_SENDS:
        raise ResendError
    code = _new_code()
    _stamp(challenge, code)
    challenge.send_count += 1
    challenge.save(update_fields=["code_hash", "sent_at", "expires_at", "attempts", "send_count"])
    _send(challenge, code, destination)


def verify(challenge_id, purpose: str, code: str) -> tuple[VerifyStatus, OneTimeCode | None]:
    """Check ``code``. Every call does the same hashing and comparison, found or not."""
    submitted = normalize_code(code)
    with transaction.atomic():
        try:
            challenge = OneTimeCode.objects.select_for_update().get(
                pk=challenge_id, purpose=purpose, consumed_at__isnull=True
            )
        except (OneTimeCode.DoesNotExist, ValidationError, ValueError, TypeError):
            challenge = None
        subject = challenge.pk if challenge else uuid.uuid4()
        expected = challenge.code_hash if challenge else _hash(subject, _new_code())
        matches = hmac.compare_digest(_hash(subject, submitted), expected)
        if challenge is None:
            return VerifyStatus.EXPIRED, None
        if challenge.verified_at:
            return VerifyStatus.OK, challenge
        if challenge.attempts >= settings.OTP_MAX_ATTEMPTS:
            return VerifyStatus.LOCKED, challenge
        if challenge.expires_at <= timezone.now():
            return VerifyStatus.EXPIRED, challenge
        challenge.attempts += 1
        if not matches:
            challenge.save(update_fields=["attempts"])
            return VerifyStatus.WRONG, challenge
        challenge.verified_at = timezone.now()
        challenge.save(update_fields=["attempts", "verified_at"])
        return VerifyStatus.OK, challenge


def is_verified(challenge: OneTimeCode | None) -> bool:
    """Verified recently enough that the next step (new password, sign-up) may proceed."""
    if challenge is None or challenge.verified_at is None or challenge.consumed_at is not None:
        return False
    age = timezone.now() - challenge.verified_at
    return age <= timedelta(seconds=settings.OTP_VERIFIED_TTL_SECONDS)


def consume(challenge: OneTimeCode) -> None:
    challenge.consumed_at = timezone.now()
    challenge.destination = None
    challenge.save(update_fields=["consumed_at", "destination"])


def purge_stale(*, older_than_days: int = 1) -> int:
    """Delete challenges (and the contacts they hold) that are long finished."""
    cutoff = timezone.now() - timedelta(days=older_than_days)
    deleted, _ = OneTimeCode.objects.filter(created_at__lt=cutoff).delete()
    return deleted
