"""Shared builders for the sign-up, login and recovery tests."""

import time

import pyotp

from apps.accounts.models import IdRegistry
from apps.accounts.services import registry as registry_service
from apps.accounts.services import twofactor
from tests.factories import make_admin, make_student, make_teacher


def issue_code(profile) -> str:
    """Give the profile's registry row an activation code and return its plaintext."""
    actor = make_admin()
    issued = registry_service.issue_activation_codes(
        IdRegistry.objects.filter(pk=profile.registry_id), valid_days=7, actor=actor
    )
    return issued[0].code


def claimable_student(**kwargs):
    profile = make_student(**kwargs)
    return profile, issue_code(profile)


def claimable_teacher(**kwargs):
    profile = make_teacher(**kwargs)
    return profile, issue_code(profile)


def totp_code(user, *, steps_ahead: int = 0) -> str:
    """A valid current code (or the one ``steps_ahead`` 30-second steps later)."""
    secret = user.totp_secret
    return pyotp.TOTP(secret).at(int(time.time()) + steps_ahead * twofactor.STEP_SECONDS)


def enable_totp(user) -> list[str]:
    """Turn two-factor on for ``user`` without going through the pages; returns recovery codes."""
    twofactor.begin_enrolment(user)
    codes = twofactor.confirm_enrolment(user, totp_code(user))
    assert codes is not None
    user.refresh_from_db()
    return codes
