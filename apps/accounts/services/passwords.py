"""Password rules: stronger for accounts that can see student identities (Admin, HOD)."""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import Role

MIN_LENGTH = 12
MIN_CHARACTER_CLASSES = 3


def validate_strong_password(password: str, user=None) -> None:
    """Django's validators plus a longer minimum and mixed character classes."""
    validate_password(password, user)
    errors = []
    if len(password) < MIN_LENGTH:
        errors.append(
            ValidationError(
                _("This password is too short. It must contain at least %(min)d characters."),
                code="password_too_short",
                params={"min": MIN_LENGTH},
            )
        )
    classes = sum(
        any(check(ch) for ch in password)
        for check in (str.islower, str.isupper, str.isdigit, lambda ch: not ch.isalnum())
    )
    if classes < MIN_CHARACTER_CLASSES:
        errors.append(
            ValidationError(
                _("Use at least three of: lower case, upper case, digits and symbols."),
                code="password_too_simple",
            )
        )
    if errors:
        raise ValidationError(errors)


def validate_account_password(password: str, user=None, *, role: str | None = None) -> None:
    """The rule that fits the account: strong for Admin and HOD, Django's validators otherwise."""
    role = role or getattr(user, "role", None)
    if role == Role.ADMIN or getattr(user, "requires_second_factor", False):
        validate_strong_password(password, user)
    else:
        validate_password(password, user)
