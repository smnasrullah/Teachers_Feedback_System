"""TOTP (RFC 6238) enrolment and verification, plus single-use recovery codes.

The secret is encrypted at rest and shown once at enrolment. A TOTP code is accepted at
most once (``totp_last_step`` only moves forward); recovery codes are stored as keyed
hashes and burned on use. Nothing here logs a secret or a code.
"""

import hmac
import secrets
import time
import unicodedata
from dataclasses import dataclass

import pyotp
import segno
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import RecoveryCode, User
from apps.accounts.services.identifiers import BANGLA_DIGITS, CODE_ALPHABET
from apps.core.encryption import blind_index

STEP_SECONDS = 30
WINDOW_STEPS = 1  # one step either side, for clock drift
RECOVERY_CODE_COUNT = 8
RECOVERY_LENGTH = 10
RECOVERY_GROUP = 5
RECOVERY_PURPOSE = "auth.recovery_code"
TOTP_DIGITS = 6
# A QR code must be dark on light to scan, whatever the page theme.
QR_DARK = "#000000"
QR_LIGHT = "#ffffff"


@dataclass(frozen=True)
class SecondFactor:
    """What a submitted second-factor code turned out to be."""

    ok: bool
    recovery: bool = False
    recovery_left: int = 0


def normalize_code(value: str) -> str:
    """Upper case, Bangla digits to ASCII, no spaces or hyphens."""
    text = unicodedata.normalize("NFKC", value).translate(BANGLA_DIGITS)
    return "".join(ch for ch in text.upper() if ch.isalnum())


def _totp(secret: str) -> pyotp.TOTP:
    return pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=STEP_SECONDS)


def begin_enrolment(user: User) -> str:
    """Give ``user`` a not-yet-active secret (the same one until it is confirmed)."""
    if user.totp_enabled:
        raise ValueError("Two-factor authentication is already enabled.")
    if not user.totp_secret:
        user.totp_secret = pyotp.random_base32()
        user.totp_last_step = 0
        user.save(update_fields=["totp_secret", "totp_last_step"])
    return user.totp_secret


def provisioning_uri(user: User) -> str:
    return _totp(user.totp_secret).provisioning_uri(
        name=user.username, issuer_name=settings.TOTP_ISSUER
    )


def qr_data_uri(user: User) -> str:
    """The enrolment QR code as an inline SVG image (allowed by the CSP's ``img-src data:``)."""
    code = segno.make(provisioning_uri(user), error="m")
    return code.svg_data_uri(scale=5, border=2, dark=QR_DARK, light=QR_LIGHT)


def manual_key(user: User) -> str:
    """The secret in groups of four, for typing into an authenticator by hand."""
    secret = user.totp_secret
    return " ".join(secret[i : i + 4] for i in range(0, len(secret), 4))


def _matching_step(secret: str, code: str, after: int) -> int | None:
    """The time step ``code`` is valid for (later than ``after``), checked in constant time."""
    totp = _totp(secret)
    now_step = int(time.time()) // STEP_SECONDS
    found = None
    for step in range(now_step - WINDOW_STEPS, now_step + WINDOW_STEPS + 1):
        if hmac.compare_digest(totp.at(step * STEP_SECONDS), code) and step > after:
            found = step
    return found


def verify_totp(user: User, code: str) -> bool:
    """Accept a current 6-digit code once; a replay of the same code fails."""
    code = normalize_code(code)
    if len(code) != TOTP_DIGITS or not code.isdigit() or not user.totp_secret:
        return False
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        step = _matching_step(locked.totp_secret, code, locked.totp_last_step)
        if step is None:
            return False
        locked.totp_last_step = step
        locked.save(update_fields=["totp_last_step"])
    user.totp_last_step = step
    return True


def _new_recovery_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(RECOVERY_LENGTH))
    return "-".join(raw[i : i + RECOVERY_GROUP] for i in range(0, RECOVERY_LENGTH, RECOVERY_GROUP))


def _recovery_hash(code: str) -> str:
    return blind_index(normalize_code(code), RECOVERY_PURPOSE)


def recovery_codes_left(user: User) -> int:
    return user.recovery_codes.filter(used_at__isnull=True).count()


def _issue_recovery_codes(user: User) -> list[str]:
    user.recovery_codes.all().delete()
    codes = [_new_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    RecoveryCode.objects.bulk_create(
        [RecoveryCode(user=user, code_hash=_recovery_hash(code)) for code in codes]
    )
    return codes


def regenerate_recovery_codes(user: User) -> list[str]:
    """Replace every recovery code with eight new ones (returned once, never stored)."""
    if not user.totp_enabled:
        raise ValueError("Recovery codes belong to an account with two-factor enabled.")
    with transaction.atomic():
        return _issue_recovery_codes(user)


def confirm_enrolment(user: User, code: str) -> list[str] | None:
    """Turn two-factor on if ``code`` matches the pending secret; returns the recovery codes."""
    if user.totp_enabled or not user.totp_secret or not verify_totp(user, code):
        return None
    with transaction.atomic():
        user.totp_enabled = True
        user.save(update_fields=["totp_enabled"])
        return _issue_recovery_codes(user)


def disable(user: User) -> None:
    with transaction.atomic():
        user.recovery_codes.all().delete()
        user.totp_secret = None
        user.totp_enabled = False
        user.totp_last_step = 0
        user.save(update_fields=["totp_secret", "totp_enabled", "totp_last_step"])


def use_recovery_code(user: User, code: str) -> bool:
    """Burn one recovery code; the conditional update makes a second use impossible."""
    normalized = normalize_code(code)
    if len(normalized) != RECOVERY_LENGTH:
        return False
    burned = user.recovery_codes.filter(
        code_hash=_recovery_hash(normalized), used_at__isnull=True
    ).update(used_at=timezone.now())
    return burned == 1


def check_second_factor(user: User, code: str) -> SecondFactor:
    """A TOTP code or a recovery code, whichever ``code`` is."""
    if verify_totp(user, code):
        return SecondFactor(ok=True)
    if use_recovery_code(user, code):
        return SecondFactor(ok=True, recovery=True, recovery_left=recovery_codes_left(user))
    return SecondFactor(ok=False)
