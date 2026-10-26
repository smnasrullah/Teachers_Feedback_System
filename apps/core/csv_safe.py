"""CSV cells that spreadsheets would otherwise run as formulas (BLUEPRINT §5.4)."""

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text
