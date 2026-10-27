"""Demo feedback: the question bank, the two rounds, and the synthetic submissions.

Every submission goes through ``submit_feedback`` with a synthetic student, so receipts,
anonymous responses, the comment filter and the audit trail behave exactly as in real use. No
response or answer row is ever written directly.
"""

import random
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

from django.utils import timezone

from apps.academics.models import CourseOffering
from apps.accounts.models import StudentProfile
from apps.core.services.demo import constants as c
from apps.core.services.demo.academics import Structure
from apps.feedback.models import (
    Answer,
    FeedbackWindow,
    ModerationStatus,
    Question,
    QuestionType,
    SubmissionReceipt,
)
from apps.feedback.services import question_bank, review
from apps.feedback.services.submit import NO, YES, submit_feedback
from apps.reports.models import ActionNote
from apps.reports.services import teacher as teacher_report

BANK_FILE = Path(__file__).with_name("question_bank.md")
SUMMER_ROUND_OPENED_DAYS, SUMMER_ROUND_CLOSES_DAYS = 3, 12
HELD_OPEN = timedelta(hours=1)
RATING_SPREAD = 0.9
QUESTION_SHIFT = 0.15  # each question is a little easier or harder than the teacher's average
POSITIVE_SHARE = 0.7
NEUTRAL_SHARE = 0.3


@dataclass(frozen=True)
class Item:
    """One form to submit."""

    student: StudentProfile
    offering: CourseOffering
    key: str
    abusive: bool = False


def _normal(text: str) -> str:
    return " ".join(text.split()).casefold()


def ensure_bank(actor) -> bool:
    """Load the demo questions unless the bank already holds questions of the owner's own.

    The seeded placeholders do not count as the owner's. Returns whether it loaded anything.
    """
    markdown = BANK_FILE.read_text(encoding="utf-8")
    demo = {_normal(row.text) for row in question_bank.parse(markdown).questions}
    placeholders = {
        _normal(text) for _category, text, _kind in question_bank.PLACEHOLDER_QUESTIONS
    } - demo
    present = {
        _normal(text)
        for text in Question.objects.filter(superseded_by__isnull=True).values_list(
            "text", flat=True
        )
    }
    if present - demo - placeholders:
        return False  # the owner has questions of their own: keep them
    if demo <= present and not present & placeholders:
        return False  # already loaded
    question_bank.load(markdown, actor=actor, replace_placeholders=True)
    return True


def ensure_rounds(structure: Structure) -> tuple[FeedbackWindow, FeedbackWindow]:
    """The closed round of the previous semester and the open round of the current one."""
    now = timezone.now()
    zone = timezone.get_default_timezone()
    opens, closes = (datetime.combine(day, time.min, tzinfo=zone) for day in c.WINTER_ROUND_DATES)
    closed = FeedbackWindow.objects.get_or_create(
        semester=structure.semesters[c.WINTER],
        name=c.WINTER_ROUND,
        defaults={"opens_at": opens, "closes_at": closes},
    )[0]
    open_ = FeedbackWindow.objects.get_or_create(
        semester=structure.semesters[c.SUMMER],
        name=c.SUMMER_ROUND,
        defaults={
            "opens_at": now - timedelta(days=SUMMER_ROUND_OPENED_DAYS),
            "closes_at": now + timedelta(days=SUMMER_ROUND_CLOSES_DAYS),
        },
    )[0]
    return closed, open_


# --- who submits ------------------------------------------------------------------------------


def closed_round_items(window, offerings, cse, eee) -> list[Item]:
    """Winter: at least nine CSE students per offering, a handful of EEE ones."""
    items = []
    groups = (
        (c.WINTER_CSE_COURSES, c.CSE_WINTER_RESPONSES, cse),
        (c.WINTER_EEE_COURSES, c.EEE_WINTER_RESPONSES, eee),
    )
    for codes, counts, students in groups:
        for code, count in zip(codes, counts, strict=True):
            rng = random.Random(f"closed:{code}")  # noqa: S311 - demo data, not security
            chosen = set(rng.sample(range(len(students)), count))
            chosen |= {index for index, abusive_code in c.ABUSIVE if abusive_code == code}
            for index in sorted(chosen):
                items.append(
                    Item(
                        students[index],
                        offerings[c.WINTER, code],
                        f"{window.name}:{index}:{code}",
                        abusive=(index, code) in c.ABUSIVE,
                    )
                )
    return items


def open_round_items(window, offerings, cse) -> list[Item]:
    """Summer: demo_student has two forms sealed; most others have some; the spare accounts none."""
    items = []
    for index, student in enumerate(cse):
        if index >= len(cse) - c.SPARE_STUDENTS:
            continue
        for code in c.SUMMER_COURSES:
            rng = random.Random(f"open:{index}:{code}")  # noqa: S311 - demo data, not security
            takes = (
                code in c.DEMO_STUDENT_SEALED if index == 0 else rng.random() < c.OPEN_SUBMIT_SHARE
            )
            if takes:
                items.append(
                    Item(student, offerings[c.SUMMER, code], f"{window.name}:{index}:{code}")
                )
    return items


# --- what they answer -------------------------------------------------------------------------


def _comment(rng, mean) -> str:
    share = (mean - 1) / 4
    roll = rng.random()
    if roll < NEUTRAL_SHARE:
        pool = c.NEUTRAL
    else:
        pool = c.POSITIVE if roll < NEUTRAL_SHARE + POSITIVE_SHARE * share else c.NEGATIVE
    return rng.choice(pool)


def _answer(question, mean, rng, abusive_text: bool):
    """A raw answer for ``question``, or ``None`` to leave an optional one blank."""
    match question.question_type:
        case QuestionType.RATING | QuestionType.LIKERT:
            shift = ((question.pk * 7) % 5 - 2) * QUESTION_SHIFT
            return min(5, max(1, round(rng.gauss(mean + shift, RATING_SPREAD))))
        case QuestionType.YES_NO:
            return YES if rng.random() < (mean - 1) / 4 + 0.1 else NO
        case QuestionType.CHOICE:
            values = [option["value"] for option in question.options]
            return values[0] if rng.random() < (mean - 1) / 4 else rng.choice(values)
        case _:
            if abusive_text:
                return rng.choice(c.ABUSIVE_COMMENTS)
            if question.required or rng.random() < c.COMMENT_SHARE:
                return _comment(rng, mean)
            return None


def _answers(item: Item, questions, mean: float) -> dict:
    rng = random.Random(item.key)  # noqa: S311 - demo data, not security
    answers, first_text = {}, True
    for question in questions:
        abusive_text = item.abusive and first_text and question.question_type == QuestionType.TEXT
        first_text = first_text and question.question_type != QuestionType.TEXT
        value = _answer(question, mean, rng, abusive_text)
        if value is not None:
            answers[question.pk] = value
    return answers


@contextmanager
def _held_open(window):
    """Let the service accept submissions for a round that is not open now, then put it back."""
    if window.is_open(timezone.now()):
        yield
        return
    now = timezone.now()
    FeedbackWindow.objects.filter(pk=window.pk).update(
        is_active=True, opens_at=now - HELD_OPEN, closes_at=now + HELD_OPEN
    )
    try:
        yield
    finally:
        FeedbackWindow.objects.filter(pk=window.pk).update(
            is_active=window.is_active, opens_at=window.opens_at, closes_at=window.closes_at
        )


def submit_all(window, items, means: dict[int, float]) -> int:
    """Submit the forms that have no receipt yet; returns how many were new."""
    done = set(
        SubmissionReceipt.objects.filter(window=window).values_list(
            "student_profile_id", "offering_id"
        )
    )
    todo = [item for item in items if (item.student.pk, item.offering.pk) not in done]
    if not todo:
        return 0
    bank = {}
    with _held_open(window):
        for item in todo:
            kind = item.offering.course.course_type
            if kind not in bank:
                bank[kind] = list(Question.objects.for_offering(item.offering))
            answers = _answers(item, bank[kind], means[item.offering.teacher_id])
            submit_feedback(item.student, item.offering, window, answers, reauth_ok=True)
    return len(todo)


# --- what happens after the round closed ------------------------------------------------------


def add_notes(window, offerings) -> None:
    """A couple of "action taken" notes written by teachers once the results were out."""
    for code, text in c.NOTES.items():
        offering = offerings[c.WINTER, code]
        if not ActionNote.objects.filter(offering=offering, window=window).exists():
            teacher_report.save_note(offering, window, text)


def moderate(window, actor) -> None:
    """Approve one cleaned comment and hide another; the rest stay in the Admin's queue."""
    flagged = Answer.objects.filter(
        response__window=window, flagged=True, moderation=ModerationStatus.UNREVIEWED
    ).order_by("pk")
    for answer_id, decision in zip(
        flagged.values_list("pk", flat=True)[:2],
        (review.Decision.APPROVE, review.Decision.HIDE),
        strict=False,
    ):
        review.decide(answer_id, decision, actor=actor)
