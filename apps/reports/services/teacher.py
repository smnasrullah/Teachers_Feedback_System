"""Teacher report data: the course overview of a round and the full report of one course.

Nothing here reads who answered. Every number comes from ``apps.analytics``, which holds back
unreleased rounds and groups below the response threshold; this module only arranges the
results for the page. ``BarRow`` and the question blocks feed server-rendered SVG bars that
the PDF export reuses.
"""

from dataclasses import dataclass

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.academics.models import CourseOffering
from apps.analytics import services as analytics
from apps.analytics.services import InsufficientData
from apps.core.services.localize import pick
from apps.feedback.models import SCALE_MAX, Answer, FeedbackWindow, Question, QuestionType
from apps.reports.models import ActionNote
from apps.reports.services.comments import CommentPanel, CommentQuery, comment_panel

MIN_RADAR_AXES = 3
MIN_TREND_POINTS = 2
INSIGHT_LIMIT = 2
STRONG_SCORE = 4.0


@dataclass(frozen=True)
class BarRow:
    label: str
    count: int
    percent: float


@dataclass(frozen=True)
class QuestionBlock:
    number: int
    question: Question
    kind: str
    count: int = 0
    average: float | None = None
    rows: tuple[BarRow, ...] = ()
    panel: CommentPanel | None = None
    notice: object = ""


@dataclass(frozen=True)
class CategoryRow:
    name: str
    score: float
    department: float | None

    @property
    def gap(self) -> float:
        return self.score - (self.department if self.department is not None else self.score)


@dataclass(frozen=True)
class CourseSummary:
    offering: CourseOffering
    released: bool
    notice: object = ""
    average: float | None = None
    rate: analytics.ResponseRate | None = None
    pending: int | None = None


@dataclass(frozen=True)
class Report:
    offering: CourseOffering
    window: FeedbackWindow
    summary: CourseSummary
    blocks: tuple[QuestionBlock, ...] = ()
    categories: tuple[CategoryRow, ...] = ()
    radar: dict | None = None
    trend: dict | None = None
    strengths: tuple[CategoryRow, ...] = ()
    improve: tuple[CategoryRow, ...] = ()
    department_average: float | None = None
    cloud: tuple[analytics.CloudWord, ...] = ()
    note: ActionNote | None = None

    @property
    def radar_summary(self) -> str:
        return _chart_summary(self.radar)

    @property
    def trend_summary(self) -> str:
        return _chart_summary(self.trend)


def _chart_summary(config) -> str:
    """The numbers of a chart as one sentence, for its text alternative."""
    if not config:
        return ""
    return "; ".join(
        f"{dataset['label']}: "
        + ", ".join(
            f"{label} {value}"
            for label, value in zip(config["labels"], dataset["data"], strict=True)
        )
        for dataset in config["datasets"]
    )


# --- rounds and the overview -----------------------------------------------------------------


def rounds_for(profile, now) -> list[FeedbackWindow]:
    """Started, active rounds that cover at least one offering of the teacher, newest first."""
    offerings = list(
        CourseOffering.objects.filter(teacher=profile).select_related("course", "semester")
    )
    windows = (
        FeedbackWindow.objects.filter(
            semester__in={offering.semester for offering in offerings},
            is_active=True,
            opens_at__lte=now,
        )
        .select_related("semester")
        .prefetch_related("departments", "level_terms")
    )
    return [w for w in windows if any(w.covers(offering) for offering in offerings)]


def pick_round(rounds, requested_id, now) -> FeedbackWindow | None:
    """The requested round, else the newest closed one, else the newest."""
    by_id = {window.pk: window for window in rounds}
    if requested_id in by_id:
        return by_id[requested_id]
    closed = [window for window in rounds if window.has_closed(now)]
    return (closed or rounds or [None])[0]


def overall_average(stats) -> float | None:
    """The mean of every rating and agreement answer, weighted by how many were given."""
    rated = [
        entry
        for entry in stats.values()
        if not isinstance(entry, InsufficientData) and entry.average is not None
    ]
    count = sum(entry.count for entry in rated)
    if not count:
        return None
    return round(sum(entry.average * entry.count for entry in rated) / count, 1)


def summarize(offering, window, viewer, now) -> CourseSummary:
    stats = analytics.question_stats(window, offering, viewer=viewer, now=now)
    if isinstance(stats, InsufficientData):
        return CourseSummary(offering, released=window.has_closed(now), notice=stats.message)
    rate = analytics.response_rate(window, offering, viewer=viewer, now=now)
    if isinstance(rate, InsufficientData):
        return CourseSummary(offering, released=True, notice=rate.message)
    return CourseSummary(
        offering,
        released=True,
        average=overall_average(stats),
        rate=rate,
        pending=max(0, rate.enrolled - rate.submitted),
    )


def overview(profile, window, viewer, now) -> list[CourseSummary]:
    """Summaries of the teacher's offerings that ``window`` covers. A round still open gives
    no figure at all, not even a count of who is still pending."""
    offerings = (
        CourseOffering.objects.filter(teacher=profile, semester=window.semester)
        .select_related("course", "semester")
        .order_by("course__code", "section")
    )
    return [
        summarize(offering, window, viewer, now)
        for offering in offerings
        if window.covers(offering)
    ]


# --- one course ------------------------------------------------------------------------------


def _choice_label(question, value) -> str:
    if question.question_type == QuestionType.YES_NO:
        return _("Yes") if value == "yes" else _("No")
    for option in question.options:
        if option.get("value") == value:
            return pick(option.get("en", value), option.get("bn", ""))
    return str(value)


def _block(number, question, stats, panel) -> QuestionBlock:
    kind = question.question_type
    if kind == QuestionType.TEXT:
        return QuestionBlock(number, question, kind, panel=panel)
    if isinstance(stats, InsufficientData):
        return QuestionBlock(number, question, kind, notice=stats.message)
    if kind in analytics.RATED_TYPES:
        # Five stars first.
        rows = tuple(
            BarRow(str(bucket.value), bucket.count, bucket.percent)
            for bucket in sorted(stats.distribution, key=lambda bucket: -bucket.value)
        )
    else:
        rows = tuple(
            BarRow(_choice_label(question, bucket.value), bucket.count, bucket.percent)
            for bucket in stats.distribution
        )
    return QuestionBlock(
        number, question, kind, count=stats.count, average=stats.average, rows=rows
    )


def _text_question_ids(window, offering) -> set[int]:
    return set(
        Answer.objects.filter(
            response__window=window,
            response__offering=offering,
            question__question_type=QuestionType.TEXT,
            encrypted_text__isnull=False,
        )
        .values_list("question_id", flat=True)
        .distinct()
    )


def _blocks(window, offering, stats, viewer, now, focus, everything) -> tuple[QuestionBlock, ...]:
    ids = set(stats) | _text_question_ids(window, offering)
    questions = Question.objects.filter(pk__in=ids).select_related("category")
    blocks = []
    for number, question in enumerate(questions, start=1):
        panel = None
        if question.question_type == QuestionType.TEXT:
            query = focus[1] if focus and focus[0] == question.pk else CommentQuery()
            panel = comment_panel(
                window, offering, question, query, viewer=viewer, now=now, everything=everything
            )
        blocks.append(_block(number, question, stats.get(question.pk), panel))
    return tuple(blocks)


def _categories(window, offering, viewer, now) -> tuple[CategoryRow, ...]:
    scores = analytics.category_scores(window, offering, viewer=viewer, now=now)
    if isinstance(scores, InsufficientData):
        return ()
    department = analytics.department_category_scores(
        window, offering.course.department, viewer=viewer, now=now
    )
    peers = {} if isinstance(department, InsufficientData) else department
    return tuple(
        CategoryRow(pick(score.name, score.name_bn), score.average, peers.get(pk))
        for pk, score in scores.items()
        if not isinstance(score, InsufficientData)
    )


def _insights(categories) -> tuple[tuple[CategoryRow, ...], tuple[CategoryRow, ...]]:
    """Strengths and places to improve: against the department average when every category
    has one, else against a fixed bar."""
    if categories and all(row.department is not None for row in categories):
        strong = sorted((row for row in categories if row.gap > 0), key=lambda r: -r.gap)
        weak = sorted((row for row in categories if row.gap < 0), key=lambda r: r.gap)
    else:
        strong = sorted((r for r in categories if r.score >= STRONG_SCORE), key=lambda r: -r.score)
        weak = sorted((r for r in categories if r.score < STRONG_SCORE), key=lambda r: r.score)
    return tuple(strong[:INSIGHT_LIMIT]), tuple(weak[:INSIGHT_LIMIT])


def _radar(categories) -> dict | None:
    if len(categories) < MIN_RADAR_AXES:
        return None
    datasets = [
        {"label": _("This course"), "data": [row.score for row in categories], "color": "primary"}
    ]
    if all(row.department is not None for row in categories):
        datasets.append(
            {
                "label": _("Department average"),
                "data": [row.department for row in categories],
                "color": "subtle",
                "borderDash": [5, 4],
                "fill": False,
            }
        )
    return {
        "type": "radar",
        "labels": [row.name for row in categories],
        "datasets": datasets,
        "scale": {"min": 0, "max": SCALE_MAX},
    }


def _trend(offering, viewer, now) -> dict | None:
    points = analytics.trend(
        teacher=offering.teacher, course=offering.course, viewer=viewer, now=now
    )
    if isinstance(points, InsufficientData) or len(points) < MIN_TREND_POINTS:
        return None
    return {
        "type": "line",
        "labels": [f"{point.semester_name} · {point.window_name}" for point in points],
        "datasets": [
            {
                "label": _("Average rating"),
                "data": [point.average for point in points],
                "color": "primary",
            }
        ],
        "scale": {"min": 1, "max": SCALE_MAX},
    }


def build_report(offering, window, viewer, now=None, *, focus=None, everything=False) -> Report:
    """The report of ``offering`` in ``window``.

    ``focus`` is ``(question id, CommentQuery)`` for the question whose comments are being
    searched or paged; ``everything`` lists all comments unpaged (the print view). A round
    still open, or a group below the threshold, gives a report with only its summary.
    """
    now = now or timezone.now()
    summary = summarize(offering, window, viewer, now)
    if summary.rate is None:
        return Report(offering, window, summary)
    department = offering.course.department
    stats = analytics.question_stats(window, offering, viewer=viewer, now=now)
    categories = _categories(window, offering, viewer, now)
    peers = analytics.department_average(window, department, viewer=viewer, now=now)
    cloud = analytics.word_cloud(window, offering, viewer=viewer, now=now)
    strengths, improve = _insights(categories)
    return Report(
        offering,
        window,
        summary,
        blocks=_blocks(window, offering, stats, viewer, now, focus, everything),
        categories=categories,
        radar=_radar(categories),
        trend=_trend(offering, viewer, now),
        strengths=strengths,
        improve=improve,
        department_average=None if isinstance(peers, InsufficientData) else peers.average,
        cloud=()
        if isinstance(cloud, InsufficientData)
        else tuple(sorted(cloud, key=lambda word: word.word)),
        note=ActionNote.objects.filter(offering=offering, window=window).first(),
    )


def save_note(offering, window, text, now=None) -> ActionNote | None:
    """Store the teacher's note for a closed round; an empty text removes it."""
    if not window.has_closed(now or timezone.now()):
        raise ValueError("Notes can be written once the round has closed.")
    text = text.strip()
    if not text:
        ActionNote.objects.filter(offering=offering, window=window).delete()
        return None
    note, _created = ActionNote.objects.update_or_create(
        offering=offering, window=window, defaults={"text": text}
    )
    return note
