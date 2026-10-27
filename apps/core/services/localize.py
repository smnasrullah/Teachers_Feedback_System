"""Pick the Bangla or English wording of a stored bilingual value."""

from django.conf import settings
from django.utils.translation import get_language

BANGLA_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


def _bangla_active() -> bool:
    return (get_language() or "").startswith("bn")


def pick(english: str, bangla: str) -> str:
    """``bangla`` when the active language is Bangla and it is filled in, else ``english``."""
    if bangla and _bangla_active():
        return bangla
    return english


def localize_digits(text: str) -> str:
    """``text`` with Bangla digits when the active language is Bangla ("2026" -> "২০২৬")."""
    return text.translate(BANGLA_DIGITS) if _bangla_active() else text


def remember_language(response, request, language: str) -> None:
    """Make ``language`` the one this browser uses from now on (a no-op for unknown codes)."""
    if language not in dict(settings.LANGUAGES):
        return
    response.set_cookie(
        settings.LANGUAGE_COOKIE_NAME,
        language,
        max_age=settings.LANGUAGE_COOKIE_AGE,
        samesite=settings.LANGUAGE_COOKIE_SAMESITE,
        secure=request.is_secure(),
    )
