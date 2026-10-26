"""What an export holds, whatever the file format.

A builder turns a report into ``Export``: plain tables, bar charts and notices. The CSV, Excel
and PDF writers only lay it out, so the three formats can never disagree on a number, a
hidden group or a column. Nothing in it identifies a response: no ids, no times.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class Format(StrEnum):
    CSV = "csv"
    XLSX = "xlsx"
    PDF = "pdf"


@dataclass(frozen=True)
class Table:
    title: str
    headers: tuple[str, ...]
    rows: tuple[tuple, ...]


@dataclass(frozen=True)
class Bar:
    label: str
    count: int | float
    percent: float


@dataclass(frozen=True)
class Chart:
    """Horizontal bars. ``stars`` labels rows "N star"; ``scores`` shows ``count`` as a score
    out of five instead of a number of answers."""

    title: str
    bars: tuple[Bar, ...]
    stars: bool = False
    scores: bool = False


@dataclass(frozen=True)
class Export:
    """``kind`` and ``name`` build the file name; ``audit`` is the small, content-free
    metadata recorded with the audit event."""

    kind: str
    name: str
    title: str
    subtitle: str
    tables: tuple[Table, ...]
    charts: tuple[Chart, ...] = ()
    notices: tuple[str, ...] = ()
    audit: dict = field(default_factory=dict)
