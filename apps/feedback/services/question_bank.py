"""Read ``docs/QUESTION_BANK.md`` and upsert it into the question bank.

The file holds one markdown table of questions and a "Rating topics" bullet list. Parsing
never touches the database; ``load`` does, idempotently: a question is matched by its
English text, so loading the same file twice changes nothing.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.auditlog.services import audit
from apps.feedback.models import AppliesTo, Question, QuestionCategory, QuestionType
from apps.feedback.services import questions

COLUMNS = 9  # #, category, text EN, text BN, type, required, applies, options EN, options BN
UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
SEPARATOR_CELL = re.compile(r":?-{3,}:?")
FENCE = "```"
TOPICS_HEADING = re.compile(r"^#+\s*rating topics\b", re.IGNORECASE)
TRUE_WORDS = {"yes": True, "y": True, "no": False, "n": False}
PLACEHOLDER_QUESTIONS = (
    ("Teaching", "The teacher explains concepts clearly.", QuestionType.RATING),
    ("Teaching", "The teacher is well prepared for class.", QuestionType.RATING),
    ("Teaching", "The teacher encourages questions and discussion.", QuestionType.LIKERT),
    ("Course Content", "The course content is relevant to the program.", QuestionType.LIKERT),
    ("Course Content", "The course materials are easy to follow.", QuestionType.RATING),
    ("Assessment", "Exams and assignments match what was taught.", QuestionType.LIKERT),
    ("Assessment", "Marks and feedback are returned in reasonable time.", QuestionType.YES_NO),
    ("Behaviour", "The teacher treats every student respectfully.", QuestionType.LIKERT),
    ("Behaviour", "The teacher starts and ends classes on time.", QuestionType.YES_NO),
    ("Overall", "Overall, how would you rate this course?", QuestionType.RATING),
    ("Overall", "Overall, how would you rate this teacher?", QuestionType.RATING),
    ("Overall", "Is there anything else you would like to tell us?", QuestionType.TEXT),
)


@dataclass(frozen=True)
class ParsedQuestion:
    line: int
    position: int | None
    category: str
    text: str
    text_bn: str
    question_type: str
    required: bool
    applies_to: str
    options: tuple[tuple[str, str], ...]  # (English, Bangla) pairs


@dataclass(frozen=True)
class Skipped:
    line: int
    reason: str


@dataclass
class ParsedBank:
    questions: list[ParsedQuestion] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)


@dataclass
class LoadReport:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    categories: int = 0
    placeholders: int = 0
    skipped: list[Skipped] = field(default_factory=list)


def _cells(line: str) -> list[str]:
    parts = UNESCAPED_PIPE.split(line.strip())
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [part.replace("\\|", "|").strip() for part in parts]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(SEPARATOR_CELL.fullmatch(cell) for cell in cells)


def _split_options(raw: str) -> list[str]:
    return [item.strip() for item in raw.split("/") if item.strip()]


def _parse_row(number: int, cells: list[str]) -> ParsedQuestion | Skipped:
    if len(cells) != COLUMNS:
        return Skipped(
            number,
            _("Expected %(want)d columns, found %(got)d.")
            % {
                "want": COLUMNS,
                "got": len(cells),
            },
        )
    position, category, text, text_bn, kind, required, applies, options_en, options_bn = cells
    if not text:
        return Skipped(number, _("No question text."))
    if not category:
        return Skipped(number, _("No category."))
    kind = kind.lower()
    if kind not in QuestionType.values:
        return Skipped(number, _("Unknown type %(value)r.") % {"value": kind})
    if required and required.lower() not in TRUE_WORDS:
        return Skipped(number, _("Required must be yes or no."))
    applies = (applies or AppliesTo.ALL.value).lower()
    if applies not in AppliesTo.values:
        return Skipped(number, _("Unknown applies value %(value)r.") % {"value": applies})
    english, bangla = _split_options(options_en), _split_options(options_bn)
    if kind != QuestionType.CHOICE and (english or bangla):
        return Skipped(number, _("Only choice questions have options."))
    if kind == QuestionType.CHOICE and len(english) < 2:
        return Skipped(number, _("A choice question needs at least two options."))
    if bangla and len(bangla) != len(english):
        return Skipped(number, _("English and Bangla options differ in number."))
    return ParsedQuestion(
        line=number,
        position=int(position) if position.isdecimal() else None,
        category=" ".join(category.split()),
        text=" ".join(text.split()),
        text_bn=" ".join(text_bn.split()),
        question_type=kind,
        required=TRUE_WORDS[required.lower()] if required else True,
        applies_to=applies,
        options=tuple(zip(english, bangla or [""] * len(english), strict=True)),
    )


def parse(markdown: str) -> ParsedBank:
    """Split the file into question rows, skipped rows (with reasons) and rating topics."""
    bank = ParsedBank()
    in_fence = in_topics = False
    in_table = seen_header = False
    for number, line in enumerate(markdown.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(FENCE):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if stripped.startswith("#"):
            in_topics = bool(TOPICS_HEADING.match(stripped))
            in_table = False
            continue
        if in_topics:
            topic = stripped.removeprefix("-").removeprefix("*").strip()
            if stripped[:1] in "-*" and topic and not topic.startswith("("):
                bank.topics.append(" ".join(topic.split()))
            continue
        if not stripped.startswith("|"):
            in_table = seen_header = False
            continue
        cells = _cells(stripped)
        if not in_table:
            in_table, seen_header = True, False
        if not seen_header:
            seen_header = True  # the header row (and the separator after it) is never data
            continue
        if _is_separator(cells):
            continue
        if not any(cells[1:]):
            bank.skipped.append(Skipped(number, _("Empty row.")))
            continue
        row = _parse_row(number, cells)
        (bank.skipped if isinstance(row, Skipped) else bank.questions).append(row)
    return bank


def _key(text: str) -> str:
    return " ".join(text.split()).casefold()


def _upsert(row: ParsedQuestion, heads: dict[str, Question], actor, order: int) -> str:
    category, _created = questions.find_or_create_category(row.category)
    existing = heads.get(_key(row.text))
    data = {
        "category": category,
        "text": row.text,
        "text_bn": row.text_bn,
        "question_type": row.question_type,
        "options": questions.build_options(
            [en for en, _bn in row.options],
            [bn for _en, bn in row.options if bn],
            existing.options if existing else (),
        ),
        "required": row.required,
        "applies_to": row.applies_to,
    }
    if existing is None:
        heads[_key(row.text)] = questions.create_question({**data, "order": order}, actor=actor)
        return "created"
    changed = any(
        getattr(existing, name) != data[name]
        for name in (*questions.LOCKED_FIELDS, *questions.EDITABLE_FIELDS)
    )
    heads[_key(row.text)] = questions.update_question(existing.pk, data, actor=actor)
    return "updated" if changed else "unchanged"


def load(markdown: str, *, actor=None) -> LoadReport:
    """Upsert ``markdown`` into the bank. Invalid rows are reported, never half-applied."""
    bank = parse(markdown)
    report = LoadReport(skipped=list(bank.skipped))
    known_categories = QuestionCategory.objects.count()
    with transaction.atomic():
        for topic in bank.topics:
            questions.find_or_create_category(topic)
        heads = {
            _key(question.text): question
            for question in Question.objects.filter(superseded_by__isnull=True)
        }
        for row in bank.questions:
            order = (row.position or len(heads) + 1) * questions.ORDER_STEP
            try:
                with transaction.atomic():
                    outcome = _upsert(row, heads, actor, order)
            except ValidationError as error:
                report.skipped.append(Skipped(row.line, "; ".join(error.messages)))
                continue
            setattr(report, outcome, getattr(report, outcome) + 1)
        report.categories = QuestionCategory.objects.count() - known_categories
        if not bank.questions and not Question.objects.exists():
            report.placeholders = _seed_placeholders(actor)
        audit.record(
            "feedback.questions_loaded",
            actor=actor,
            metadata={
                "created": report.created,
                "updated": report.updated,
                "skipped": len(report.skipped),
                "placeholders": report.placeholders,
            },
        )
    return report


def _seed_placeholders(actor) -> int:
    for position, (category, text, kind) in enumerate(PLACEHOLDER_QUESTIONS, start=1):
        questions.create_question(
            {
                "category": questions.find_or_create_category(category)[0],
                "text": text,
                "question_type": kind,
                "options": [],
                "required": kind != QuestionType.TEXT,
                "applies_to": AppliesTo.ALL,
                "order": position * questions.ORDER_STEP,
            },
            actor=actor,
        )
    return len(PLACEHOLDER_QUESTIONS)


def load_file(path: Path, *, actor=None) -> LoadReport:
    return load(path.read_text(encoding="utf-8-sig"), actor=actor)
