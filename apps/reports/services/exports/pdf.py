"""PDF files through WeasyPrint.

WeasyPrint needs native libraries (Pango) that some machines lack, so it is imported on use
and a missing install raises ``PdfUnavailable`` instead of breaking the app at start-up. The
fonts are local TTFs (``static/fonts/pdf``), embedded in the file by WeasyPrint; the page reuses
the report's server-rendered SVG bars, so no JavaScript runs.
"""

from django.conf import settings
from django.template.loader import render_to_string

from apps.reports.services.exports.model import Export

STYLESHEETS = (
    settings.BASE_DIR / "static" / "src" / "tokens.css",
    settings.BASE_DIR / "static" / "pdf" / "report.css",
)
TEMPLATE = "reports/pdf/export.html"


class PdfUnavailable(Exception):
    """WeasyPrint or its native libraries are not installed."""


def weasyprint_available() -> bool:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


def to_pdf(export: Export) -> bytes:
    try:
        from weasyprint import CSS, HTML
    except (ImportError, OSError) as error:
        raise PdfUnavailable from error
    html = render_to_string(TEMPLATE, {"export": export})
    return HTML(string=html, base_url=str(settings.BASE_DIR)).write_pdf(
        stylesheets=[CSS(filename=str(path)) for path in STYLESHEETS]
    )
