"""Pick the Bangla or English wording of a stored bilingual value."""

from django.conf import settings
from django.utils.translation import get_language

BANGLA_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
ASCII_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


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


ROMAN_NUMERALS = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X")


def to_roman(number: int | str | None) -> str:
    """A term as a Roman numeral (1..10 -> "I".."X"); any other value is shown as it is, and
    nothing as an empty string. The same in every language: a term is never in Bangla digits."""
    if number is None:
        return ""
    if isinstance(number, int) and 1 <= number <= len(ROMAN_NUMERALS):
        return ROMAN_NUMERALS[number - 1]
    return str(number)


def parse_term(text: str) -> int | None:
    """The term a person typed: digits ("2", also Bangla ones) or a Roman numeral ("ii", any
    case), 1..10 for the numeral. ``None`` when it is neither."""
    word = text.strip().translate(ASCII_DIGITS)
    if word.isascii() and word.isdigit():
        return int(word)
    try:
        return ROMAN_NUMERALS.index(word.upper()) + 1
    except ValueError:
        return None


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
