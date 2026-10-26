"""CSV cells that spreadsheets would otherwise run as formulas (BLUEPRINT §5.4)."""

import re

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


NEGATIVE_NUMBER = re.compile(r"-\d+(?:\.\d+)?")
FORMULA_LEADERS = "=+-@"


def clean_cell(value: str) -> str:
    """Neutralise an incoming CSV cell: surrounding whitespace goes, and so do any leading
    ``= + - @`` characters, unless the cell is a plain negative number (``-5``, ``-0.5``)."""
    text = value.strip()
    if not text or NEGATIVE_NUMBER.fullmatch(text):
        return text
    return text.lstrip(FORMULA_LEADERS + " \t\r").strip()
