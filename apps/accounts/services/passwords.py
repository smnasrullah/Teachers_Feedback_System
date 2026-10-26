"""Password rule for accounts that can see student identities (Admin)."""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

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
