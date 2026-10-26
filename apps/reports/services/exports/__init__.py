"""Exports of the reports: CSV, Excel and PDF files of an ``Export`` (BLUEPRINT §5.4).

A view builds the export for the signed-in viewer (``builders``), then ``deliver`` writes the
audit event and the file. The event holds the report kind, format and ids only.
"""

from dataclasses import dataclass

from django.utils.text import slugify

from apps.auditlog.services import audit
from apps.reports.services.exports import writers
from apps.reports.services.exports.model import Export, Format
from apps.reports.services.exports.pdf import to_pdf

CONTENT_TYPES = {
    Format.CSV: "text/csv; charset=utf-8",
    Format.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    Format.PDF: "application/pdf",
}
WRITERS = {Format.CSV: writers.to_csv, Format.XLSX: writers.to_xlsx, Format.PDF: to_pdf}


@dataclass(frozen=True)
class File:
    content: bytes
    content_type: str
    filename: str


def filename(export: Export, fmt: Format) -> str:
    stem = slugify(f"{export.kind}-{export.name}", allow_unicode=True) or export.kind
    return f"{stem}.{fmt.value}"


def deliver(export: Export, fmt: Format, *, request, target=None, department_id=None) -> File:
    """Render first, so a PDF that cannot be made leaves no audit event, then record it."""
    content = WRITERS[fmt](export)
    audit.record(
        "report.exported",
        request=request,
        target=target,
        department_id=department_id,
        metadata={**export.audit, "format": fmt.value},
    )
    return File(content, CONTENT_TYPES[fmt], filename(export, fmt))
