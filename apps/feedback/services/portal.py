"""What a student sees: this semester's courses with their feedback state, and the form.

Everything starts from the signed-in student's own enrollments, so a course or round that is
not theirs is simply not found (``find_target`` returns ``None``) and looks exactly like one
that does not exist.
"""

from dataclasses import dataclass
from enum import StrEnum

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.academics.models import CourseOffering, Semester
from apps.academics.services import semesters
from apps.core.services.localize import pick
from apps.feedback.models import (
    FeedbackWindow,
    Question,
    QuestionType,
    SubmissionReceipt,
    WindowStatus,
)
from apps.feedback.services import drafts
from apps.feedback.services.submit import NO, YES

SECTION_ICONS = ("book", "list", "file", "award")
FINGERPRINT_SEPARATOR = ","
SECONDS_PER_MINUTE, SECONDS_PER_HOUR, SECONDS_PER_DAY = 60, 3600, 86400


class CourseState(StrEnum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    CLOSED = "closed"
    UPCOMING = "upcoming"
    UNSCHEDULED = "unscheduled"


class FormState(StrEnum):
    OPEN = "open"
    SUBMITTED = "submitted"
    UPCOMING = "upcoming"
    CLOSED = "closed"


@dataclass(frozen=True)
class CourseEntry:
    offering: CourseOffering
    window: FeedbackWindow | None
    state: CourseState

    @property
    def can_give(self) -> bool:
        return self.state == CourseState.PENDING


@dataclass(frozen=True)
class Countdown:
    days: int
    hours: int
    minutes: int


@dataclass(frozen=True)
class RoundSummary:
    window: FeedbackWindow
    status: WindowStatus
    countdown: Countdown | None
    elapsed_percent: int
    done: int
    total: int


@dataclass(frozen=True)
class Dashboard:
    semester: Semester | None
    entries: list[CourseEntry]
    round: RoundSummary | None

    @property
    def waiting(self) -> int:
        return sum(entry.can_give for entry in self.entries)


def _pick_window(windows, now) -> FeedbackWindow | None:
    """The round that matters most: open (closing first), else upcoming (opening first),
    else the one that closed last."""
    by_status: dict[str, list[FeedbackWindow]] = {status: [] for status in WindowStatus.values}
    for window in windows:
        by_status[window.status(now)].append(window)
    if by_status[WindowStatus.OPEN]:
        return min(by_status[WindowStatus.OPEN], key=lambda window: window.closes_at)
    if by_status[WindowStatus.UPCOMING]:
        return min(by_status[WindowStatus.UPCOMING], key=lambda window: window.opens_at)
    if by_status[WindowStatus.CLOSED]:
        return max(by_status[WindowStatus.CLOSED], key=lambda window: window.closes_at)
    return None


def _course_state(window: FeedbackWindow | None, submitted: bool, now) -> CourseState:
    if window is None:
        return CourseState.UNSCHEDULED
    if submitted:
        return CourseState.SUBMITTED
    match window.status(now):
        case WindowStatus.OPEN:
            return CourseState.PENDING
        case WindowStatus.UPCOMING:
            return CourseState.UPCOMING
    return CourseState.CLOSED


def _countdown(delta) -> Countdown:
    seconds = max(0, int(delta.total_seconds()))
    days, rest = divmod(seconds, SECONDS_PER_DAY)
    hours, rest = divmod(rest, SECONDS_PER_HOUR)
    return Countdown(days, hours, rest // SECONDS_PER_MINUTE)


def _round_summary(window: FeedbackWindow, entries: list[CourseEntry], now) -> RoundSummary:
    status = WindowStatus(window.status(now))
    in_round = [entry for entry in entries if entry.window == window]
    if status == WindowStatus.OPEN:
        countdown = _countdown(window.closes_at - now)
        elapsed = (now - window.opens_at) / (window.closes_at - window.opens_at)
    elif status == WindowStatus.UPCOMING:
        countdown, elapsed = _countdown(window.opens_at - now), 0
    else:
        countdown, elapsed = None, 1
    return RoundSummary(
        window=window,
        status=status,
        countdown=countdown,
        elapsed_percent=round(100 * min(1, max(0, elapsed))),
        done=sum(entry.state == CourseState.SUBMITTED for entry in in_round),
        total=len(in_round),
    )


def build_dashboard(student_profile, now) -> Dashboard:
    """The student's courses of the current semester with the state of each one's round.

    The round card and progress ring describe the most relevant round (see
    ``_pick_window``); every course still carries the state of its own round.
    """
    semester = semesters.current_semester(timezone.localdate(now))
    if semester is None:
        return Dashboard(None, [], None)
    offerings = list(
        CourseOffering.objects.filter(
            semester=semester, enrollments__student_profile=student_profile
        )
        .select_related("course__department", "teacher__registry")
        .order_by("course__code", "section")
    )
    windows = list(
        FeedbackWindow.objects.filter(semester=semester, is_active=True).prefetch_related(
            "departments", "level_terms"
        )
    )
    submitted = set(
        SubmissionReceipt.objects.filter(
            student_profile=student_profile, offering__in=offerings
        ).values_list("offering_id", "window_id")
    )
    entries = []
    for offering in offerings:
        window = _pick_window([window for window in windows if window.covers(offering)], now)
        state = _course_state(
            window, window is not None and (offering.pk, window.pk) in submitted, now
        )
        entries.append(CourseEntry(offering, window, state))
    current = _pick_window({entry.window for entry in entries if entry.window}, now)
    summary = _round_summary(current, entries, now) if current else None
    return Dashboard(semester, entries, summary)


def find_target(student_profile, window_id: int, offering_id: int):
    """``(offering, window)`` when the student is enrolled in the offering and the round
    covers it, else ``None`` (the caller answers 404, never saying which part was wrong)."""
    offering = (
        CourseOffering.objects.select_related("course__department", "semester", "teacher__registry")
        .filter(pk=offering_id, enrollments__student_profile=student_profile)
        .first()
    )
    window = (
        FeedbackWindow.objects.prefetch_related("departments", "level_terms")
        .filter(pk=window_id, is_active=True)
        .first()
    )
    if offering is None or window is None or not window.covers(offering):
        return None
    return offering, window


def form_state(student_profile, offering, window, now) -> FormState:
    if SubmissionReceipt.objects.filter(
        student_profile=student_profile, offering=offering, window=window
    ).exists():
        return FormState.SUBMITTED
    match window.status(now):
        case WindowStatus.OPEN:
            return FormState.OPEN
        case WindowStatus.UPCOMING:
            return FormState.UPCOMING
    return FormState.CLOSED


def form_questions(offering) -> list[Question]:
    return list(Question.objects.for_offering(offering).select_related("category"))


def fingerprint(questions) -> str:
    """Identifies the exact questions a form showed, so a changed bank is noticed on submit."""
    return FINGERPRINT_SEPARATOR.join(str(question.pk) for question in questions)


def parse_answers(questions, data) -> dict[int, str]:
    """The raw answers ({question pk: text}) a posted form carries; blanks are left out."""
    answers = {}
    for question in questions:
        raw = data.get(f"q{question.pk}")
        if raw is not None and raw.strip():
            answers[question.pk] = (
                raw if question.question_type == QuestionType.TEXT else raw.strip()
            )
    return answers


def draft_values(student_profile, offering, window) -> dict[int, str]:
    return {
        pk: value if isinstance(value, str) else str(value)
        for pk, value in drafts.load_draft(student_profile, offering, window).items()
        if value is not None
    }


def error_messages(error: ValidationError) -> tuple[dict[int, list[str]], list[str]]:
    """Split a submission's ``ValidationError`` into messages per question and form-wide ones."""
    by_question, general = {}, []
    for key, messages in error.message_dict.items():
        if key == NON_FIELD_ERRORS:
            general.extend(messages)
        else:
            by_question[int(key)] = messages
    return by_question, general


@dataclass
class FormQuestion:
    question: Question
    number: int
    text: str
    options: list[tuple[str, str]]
    value: str
    errors: list[str]

    @property
    def kind(self) -> str:
        return self.question.question_type

    @property
    def field(self) -> str:
        return f"q{self.question.pk}"


@dataclass
class Section:
    title: str
    icon: str
    questions: list[FormQuestion]


def _options(question: Question) -> list[tuple[str, str]]:
    match question.question_type:
        case QuestionType.YES_NO:
            return [(YES, _("Yes")), (NO, _("No"))]
        case QuestionType.LIKERT:
            return [
                ("1", _("Strongly disagree")),
                ("2", _("Disagree")),
                ("3", _("Neutral")),
                ("4", _("Agree")),
                ("5", _("Strongly agree")),
            ]
        case QuestionType.CHOICE:
            return [
                (
                    option["value"],
                    pick(option.get("en") or option["value"], option.get("bn", "")),
                )
                for option in question.options
            ]
    return []


def form_sections(questions, values: dict[int, str], errors: dict[int, list[str]]) -> list[Section]:
    """The questions grouped by category (in category order, uncategorised last), numbered
    in the order they are shown, with the answers already given and their errors."""
    groups: dict[int | None, list[Question]] = {}
    for question in questions:
        groups.setdefault(question.category_id, []).append(question)

    def position(group):
        category = group[0].category
        return (category is None, category.order if category else 0, category.pk if category else 0)

    sections, number = [], 0
    for index, group in enumerate(sorted(groups.values(), key=position)):
        category = group[0].category
        shown = []
        for question in group:
            number += 1
            shown.append(
                FormQuestion(
                    question=question,
                    number=number,
                    text=pick(question.text, question.text_bn),
                    options=_options(question),
                    value=values.get(question.pk, ""),
                    errors=errors.get(question.pk, []),
                )
            )
        title = pick(category.name, category.name_bn) if category else _("More questions")
        sections.append(Section(title, SECTION_ICONS[index % len(SECTION_ICONS)], shown))
    return sections
