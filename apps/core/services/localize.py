"""Pick the Bangla or English wording of a stored bilingual value."""

from django.utils.translation import get_language


def pick(english: str, bangla: str) -> str:
    """``bangla`` when the active language is Bangla and it is filled in, else ``english``."""
    if bangla and (get_language() or "").startswith("bn"):
        return bangla
    return english
