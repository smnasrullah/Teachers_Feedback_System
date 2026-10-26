"""Aggregates over anonymous feedback (BLUEPRINT §5.2 A3-A5, CLAUDE.md rule 6).

Every public function takes the round (``window``) and the slice of offerings it looks at, and
returns either its result or ``InsufficientData``:

* ``NOT_RELEASED`` while the round is open, unless ``live`` is set and ``viewer`` is an Admin;
* ``TOO_FEW`` when the slice, or the part of it the result is built from, has fewer than
  ``anonymity.min_responses()`` rows. A smaller group could be told apart by elimination, so
  the number itself is never returned either.

Nothing here reads ``SubmissionReceipt`` or ``Enrollment`` in the same query as a response:
answers are read through ``response -> offering/window`` only, and the response rate counts
receipts and enrolments in queries of their own.

Results are cached per round. ``invalidate()`` replaces the round's cache version when an
answer is submitted or the round is saved, so a stale number is never served after a new
response; a round closing needs no invalidation because the release check runs on every call,
before the cache is read. Comment texts are never cached: the cache holds counts and words
that occur at least ``MIN_KEYWORD_COUNT`` times.
"""

import hashlib
import unicodedata
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import StrEnum

from django.core.cache import cache
from django.db.models import Avg, Count, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.academics.models import CourseOffering
from apps.analytics import lexicon
from apps.core.permissions import Role, has_role
from apps.enrollment.models import Enrollment
from apps.feedback.models import (
    SCALE_MAX,
    SCALE_MIN,
    Answer,
    FeedbackResponse,
    FeedbackWindow,
    Question,
    QuestionType,
    SubmissionReceipt,
)
from apps.feedback.services import anonymity, wordlist

CACHE_SECONDS = 900
MIN_DEPARTMENT_TEACHERS = 2
MIN_KEYWORD_COUNT = 2
MIN_KEYWORD_LENGTH = 3
TOP_KEYWORDS = 10
CLOUD_WORDS = 40
CLOUD_WEIGHTS = 5
APPROXIMATE_LABEL = _("Approximate: tagged from word lists, not read by a person.")
NOT_ENOUGH_MESSAGE = _("Not enough responses to show this.")
NOT_RELEASED_MESSAGE = _("Results are released after the round closes.")

RATED_TYPES = (QuestionType.RATING, QuestionType.LIKERT)


class Reason(StrEnum):
    NOT_RELEASED = "not_released"
    TOO_FEW = "too_few"


@dataclass(frozen=True)
class InsufficientData:
    reason: Reason

    @property
    def message(self):
        return NOT_RELEASED_MESSAGE if self.reason == Reason.NOT_RELEASED else NOT_ENOUGH_MESSAGE


class Sentiment(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


@dataclass(frozen=True)
class Bucket:
    value: int | str
    count: int
    percent: float


@dataclass(frozen=True)
class QuestionStats:
    question_id: int
    question_type: str
    count: int
    average: float | None
    distribution: tuple[Bucket, ...]


@dataclass(frozen=True)
class CategoryScore:
    category_id: int
    name: str
    name_bn: str
    average: float
    count: int


@dataclass(frozen=True)
class ResponseRate:
    submitted: int
    enrolled: int
    percent: float


@dataclass(frozen=True)
class TrendPoint:
    window_id: int
    window_name: str
    semester_name: str
    average: float
    count: int


@dataclass(frozen=True)
class DepartmentAverage:
    department_id: int
    average: float
    count: int


@dataclass(frozen=True)
class SentimentSummary:
    positive: int
    neutral: int
    negative: int
    approximate: bool = True

    @property
    def total(self) -> int:
        return self.positive + self.neutral + self.negative


@dataclass(frozen=True)
class Keyword:
    word: str
    count: int


@dataclass(frozen=True)
class CloudWord:
    word: str
    count: int
    weight: int


@dataclass(frozen=True)
class Comment:
    text: str
    sentiment: Sentiment


@dataclass(frozen=True)
class _TextInsights:
    sentiment: SentimentSummary
    keywords: tuple[Keyword, ...]
    cloud: tuple[CloudWord, ...]


# --- release and caching ---------------------------------------------------------------------


def offering_ids(offerings) -> tuple[int, ...]:
    """Sorted primary keys of an offering, an id or an iterable of either."""
    if isinstance(offerings, (CourseOffering, int)):
        offerings = [offerings]
    return tuple(sorted({o if isinstance(o, int) else o.pk for o in offerings}))


def _not_released(window, viewer, live, now) -> InsufficientData | None:
    """``None`` when the caller may see results of ``window`` at all."""
    if window.has_closed(now or timezone.now()):
        return None
    if live and has_role(viewer, Role.ADMIN):
        return None
    return InsufficientData(Reason.NOT_RELEASED)


def _version_key(window_id) -> str:
    return f"analytics:version:{window_id}"


def _version(window_id) -> str:
    return cache.get_or_set(_version_key(window_id), lambda: uuid.uuid4().hex, None)


def invalidate(window) -> None:
    """Drop every cached result of ``window``; call after its answers or settings change."""
    cache.set(_version_key(window.pk), uuid.uuid4().hex, None)


def _cached(versions: dict, name: str, args, compute):
    """``compute()`` once per cache version of the rounds in ``versions``' keys."""
    digest = hashlib.sha256(repr((name, args, sorted(versions))).encode()).hexdigest()
    key = f"analytics:{digest}:{':'.join(_version(window_id) for window_id in sorted(versions))}"
    result = cache.get(key)
    if result is None:
        result = compute()
        cache.set(key, result, CACHE_SECONDS)
    return result


def _enough(count: int) -> bool:
    return anonymity.enough_responses(count)


def _too_few() -> InsufficientData:
    return InsufficientData(Reason.TOO_FEW)


def _response_count(window, ids) -> int:
    return FeedbackResponse.objects.filter(window=window, offering_id__in=ids).count()


def _percent(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


# --- per question and per category -----------------------------------------------------------


def question_stats(
    window, offerings, *, viewer=None, live=False, now=None
) -> dict[int, QuestionStats | InsufficientData] | InsufficientData:
    """Count, average (rating and agreement questions), distribution and the percentage of
    each choice, per answered non-text question. A question answered by fewer people than the
    threshold is ``InsufficientData`` on its own."""
    if refusal := _not_released(window, viewer, live, now):
        return refusal
    ids = offering_ids(offerings)
    computed = _cached({window.pk}, "questions", (window.pk, ids), lambda: _tally(window, ids))
    return computed if isinstance(computed, InsufficientData) else computed[0]


def category_scores(
    window, offerings, *, viewer=None, live=False, now=None
) -> dict[int, CategoryScore | InsufficientData] | InsufficientData:
    """Mean of all rating and agreement answers per question category, in category order."""
    if refusal := _not_released(window, viewer, live, now):
        return refusal
    ids = offering_ids(offerings)
    computed = _cached({window.pk}, "questions", (window.pk, ids), lambda: _tally(window, ids))
    return computed if isinstance(computed, InsufficientData) else computed[1]


def _tally(window, ids):
    """``(stats per question, scores per category)`` of the slice, or ``InsufficientData``.

    Two queries after the response count: the answers grouped by question and value, and the
    questions they point at.
    """
    if not _enough(_response_count(window, ids)):
        return _too_few()
    rows = (
        Answer.objects.filter(response__window=window, response__offering_id__in=ids)
        .filter(Q(int_value__isnull=False) | ~Q(choice_value=""))
        .values("question_id", "int_value", "choice_value")
        .annotate(n=Count("pk"))
    )
    counts: dict[int, Counter] = defaultdict(Counter)
    for row in rows:
        counts[row["question_id"]][
            row["int_value"] if row["int_value"] is not None else row["choice_value"]
        ] += row["n"]
    questions = Question.objects.filter(pk__in=counts).select_related("category")
    stats = {
        question.pk: _question_stats(question, counts[question.pk])
        for question in sorted(questions, key=lambda q: (q.order, q.pk))
    }
    return stats, _category_scores(questions, counts)


def _question_stats(question, counter: Counter) -> QuestionStats | InsufficientData:
    total = sum(counter.values())
    if not _enough(total):
        return _too_few()
    rated = question.question_type in RATED_TYPES
    if rated:
        values = list(range(SCALE_MIN, SCALE_MAX + 1))
    elif question.question_type == QuestionType.YES_NO:
        values = ["yes", "no"]
    else:
        values = [option["value"] for option in question.options]
    values += [value for value in counter if value not in values]
    average = sum(value * n for value, n in counter.items()) / total if rated else None
    return QuestionStats(
        question_id=question.pk,
        question_type=question.question_type,
        count=total,
        average=round(average, 2) if average is not None else None,
        distribution=tuple(
            Bucket(value, counter[value], _percent(counter[value], total)) for value in values
        ),
    )


def _category_scores(questions, counts) -> dict[int, CategoryScore | InsufficientData]:
    sums: dict = defaultdict(lambda: [0, 0])
    for question in questions:
        if question.question_type in RATED_TYPES and question.category_id:
            total = sums[question.category]
            total[0] += sum(value * n for value, n in counts[question.pk].items())
            total[1] += sum(counts[question.pk].values())
    scores = {}
    for category, (points, count) in sorted(
        sums.items(), key=lambda item: (item[0].order, item[0].pk)
    ):
        scores[category.pk] = (
            CategoryScore(
                category.pk, category.name, category.name_bn, round(points / count, 2), count
            )
            if _enough(count)
            else _too_few()
        )
    return scores


# --- participation, trend, department --------------------------------------------------------


def response_rate(
    window, offerings, *, viewer=None, live=False, now=None
) -> ResponseRate | InsufficientData:
    """Receipts against enrolments. Both are counted on their own, never joined to a response."""
    if refusal := _not_released(window, viewer, live, now):
        return refusal
    ids = offering_ids(offerings)

    def compute():
        submitted = SubmissionReceipt.objects.filter(window=window, offering_id__in=ids).count()
        if not _enough(submitted):
            return _too_few()
        enrolled = Enrollment.objects.filter(offering_id__in=ids).count()
        return ResponseRate(submitted, enrolled, min(100.0, _percent(submitted, enrolled)))

    return _cached({window.pk}, "rate", (window.pk, ids), compute)


def trend(
    *, teacher=None, course=None, department=None, viewer=None, live=False, now=None
) -> list[TrendPoint] | InsufficientData:
    """Mean score of the offerings of a teacher, course or department, round by round, oldest
    first. Rounds that are not released or have too few responses are left out."""
    scope = Q()
    for field, value in (
        ("teacher", teacher),
        ("course", course),
        ("course__department", department),
    ):
        if value is not None:
            scope &= Q(**{field: value})
    if not scope:
        raise ValueError("trend() needs a teacher, a course or a department.")
    now = now or timezone.now()
    candidates = (
        FeedbackWindow.objects.filter(
            pk__in=FeedbackResponse.objects.filter(
                offering__in=CourseOffering.objects.filter(scope)
            ).values("window_id")
        )
        .select_related("semester")
        .order_by("opens_at")
    )
    windows = {
        window.pk: window for window in candidates if not _not_released(window, viewer, live, now)
    }
    if not windows:
        return InsufficientData(Reason.NOT_RELEASED if candidates else Reason.TOO_FEW)

    def compute():
        offerings = CourseOffering.objects.filter(scope)
        sizes = dict(
            FeedbackResponse.objects.filter(window_id__in=windows, offering__in=offerings)
            .values_list("window_id")
            .annotate(n=Count("pk"))
        )
        means = {
            row["response__window_id"]: row
            for row in Answer.objects.filter(
                response__window_id__in=windows,
                response__offering__in=offerings,
                int_value__isnull=False,
            )
            .values("response__window_id")
            .annotate(average=Avg("int_value"), n=Count("pk"))
        }
        return [
            TrendPoint(
                window.pk,
                window.name,
                window.semester.name,
                round(means[window.pk]["average"], 2),
                means[window.pk]["n"],
            )
            for window in windows.values()
            if _enough(sizes.get(window.pk, 0)) and window.pk in means
        ]

    points = _cached(set(windows), "trend", repr(scope), compute)
    return points or _too_few()


def department_average(
    window, department, *, viewer=None, live=False, now=None
) -> DepartmentAverage | InsufficientData:
    """Mean score across a department, with no breakdown by course or teacher. It needs
    responses about at least ``MIN_DEPARTMENT_TEACHERS`` teachers, so that it is never one
    teacher's own result."""
    if refusal := _not_released(window, viewer, live, now):
        return refusal

    def compute():
        size = FeedbackResponse.objects.filter(
            window=window, offering__course__department=department
        ).aggregate(n=Count("pk"), teachers=Count("offering__teacher", distinct=True))
        if not _enough(size["n"]) or size["teachers"] < MIN_DEPARTMENT_TEACHERS:
            return _too_few()
        mean = Answer.objects.filter(
            response__window=window,
            response__offering__course__department=department,
            int_value__isnull=False,
        ).aggregate(average=Avg("int_value"), n=Count("pk"))
        if not mean["n"]:
            return _too_few()
        return DepartmentAverage(department.pk, round(mean["average"], 2), size["n"])

    return _cached({window.pk}, "department", (window.pk, department.pk), compute)


def department_category_scores(
    window, department, *, viewer=None, live=False, now=None
) -> dict[int, float] | InsufficientData:
    """Mean score per question category across a department, for comparison with one course.
    The same floor as ``department_average`` applies, and a category needs the threshold in
    answers on its own; a category below it is left out."""
    if refusal := _not_released(window, viewer, live, now):
        return refusal

    def compute():
        size = FeedbackResponse.objects.filter(
            window=window, offering__course__department=department
        ).aggregate(n=Count("pk"), teachers=Count("offering__teacher", distinct=True))
        if not _enough(size["n"]) or size["teachers"] < MIN_DEPARTMENT_TEACHERS:
            return _too_few()
        rows = (
            Answer.objects.filter(
                response__window=window,
                response__offering__course__department=department,
                int_value__isnull=False,
                question__question_type__in=RATED_TYPES,
                question__category__isnull=False,
            )
            .values("question__category_id")
            .annotate(average=Avg("int_value"), n=Count("pk"))
        )
        return {
            row["question__category_id"]: round(row["average"], 2)
            for row in rows
            if _enough(row["n"])
        }

    return _cached({window.pk}, "department-categories", (window.pk, department.pk), compute)


# --- comments ---------------------------------------------------------------------------------


def tokens(text: str) -> list[str]:
    """The words of ``text``, folded, with no digits or symbols attached."""
    folded = wordlist.fold(text)
    words = (folded[start:end] for start, end in wordlist.word_spans(folded))
    return [word for word in map(_letters, words) if word]


def _letters(word: str) -> str:
    return "".join(char for char in word if unicodedata.category(char)[0] in "LM")


def _forms(word: str):
    yield word
    for suffix in lexicon.BANGLA_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= lexicon.MIN_STEM:
            yield word.removesuffix(suffix)


def sentiment_of(text: str) -> Sentiment:
    """A rough tag from the word lists: a positive or negative word counts one, a negator
    just before it (English) or right after it (Bangla) turns it round."""
    words = tokens(text)
    score = 0
    for index, word in enumerate(words):
        forms = set(_forms(word))
        weight = (not forms.isdisjoint(lexicon.POSITIVE)) - (not forms.isdisjoint(lexicon.NEGATIVE))
        if not weight:
            continue
        before = words[max(0, index - lexicon.NEGATION_REACH) : index]
        after = words[index + 1 : index + 2]
        if not lexicon.NEGATORS_BEFORE.isdisjoint(before) or not lexicon.NEGATORS_AFTER.isdisjoint(
            after
        ):
            weight = -weight
        score += weight
    if score > 0:
        return Sentiment.POSITIVE
    return Sentiment.NEGATIVE if score < 0 else Sentiment.NEUTRAL


def _texts(window, ids, question=None) -> list[str]:
    answers = Answer.objects.filter(
        response__window=window,
        response__offering_id__in=ids,
        question__question_type=QuestionType.TEXT,
        encrypted_text__isnull=False,
    )
    if question is not None:
        answers = answers.filter(question=question)
    return [text for text in answers.values_list("encrypted_text", flat=True) if text.strip()]


def _insights(window, ids, question) -> _TextInsights | InsufficientData:
    if not _enough(_response_count(window, ids)):
        return _too_few()
    texts = _texts(window, ids, question)
    if not _enough(len(texts)):
        return _too_few()
    tags = Counter(sentiment_of(text) for text in texts)
    words = Counter(
        word
        for text in texts
        for word in tokens(text)
        if len(word) >= MIN_KEYWORD_LENGTH and word not in lexicon.STOPWORDS
    )
    common = [(word, n) for word, n in words.most_common() if n >= MIN_KEYWORD_COUNT]
    top = common[:CLOUD_WORDS]
    biggest, smallest = (top[0][1], top[-1][1]) if top else (0, 0)
    spread = max(1, biggest - smallest)
    return _TextInsights(
        sentiment=SentimentSummary(
            tags[Sentiment.POSITIVE], tags[Sentiment.NEUTRAL], tags[Sentiment.NEGATIVE]
        ),
        keywords=tuple(Keyword(word, n) for word, n in common[:TOP_KEYWORDS]),
        cloud=tuple(
            CloudWord(word, n, 1 + round((CLOUD_WEIGHTS - 1) * (n - smallest) / spread))
            for word, n in top
        ),
    )


def _text_insights(window, offerings, question, viewer, live, now):
    if refusal := _not_released(window, viewer, live, now):
        return refusal
    ids = offering_ids(offerings)
    question_id = question.pk if question is not None else None
    return _cached(
        {window.pk},
        "text",
        (window.pk, ids, question_id),
        lambda: _insights(window, ids, question),
    )


def comment_sentiment(
    window, offerings, question=None, *, viewer=None, live=False, now=None
) -> SentimentSummary | InsufficientData:
    """How many comments read positive, neutral or negative (approximate; see
    ``APPROXIMATE_LABEL``). Needs the threshold in responses and in comments."""
    result = _text_insights(window, offerings, question, viewer, live, now)
    return result if isinstance(result, InsufficientData) else result.sentiment


def top_keywords(
    window, offerings, question=None, *, viewer=None, live=False, now=None
) -> tuple[Keyword, ...] | InsufficientData:
    """The most used words of the comments; a word used once is never listed."""
    result = _text_insights(window, offerings, question, viewer, live, now)
    return result if isinstance(result, InsufficientData) else result.keywords


def word_cloud(
    window, offerings, question=None, *, viewer=None, live=False, now=None
) -> tuple[CloudWord, ...] | InsufficientData:
    """Words with a size from 1 (smallest) to ``CLOUD_WEIGHTS``, for a word cloud."""
    result = _text_insights(window, offerings, question, viewer, live, now)
    return result if isinstance(result, InsufficientData) else result.cloud


def comment_list(
    window, offering, question, *, viewer=None, live=False, now=None
) -> list[Comment] | InsufficientData:
    """The comments on ``question`` in stable shuffled order, each with its approximate tag.
    Not cached: comment texts stay out of the cache."""
    if refusal := _not_released(window, viewer, live, now):
        return refusal
    if not _enough(_response_count(window, offering_ids(offering))):
        return _too_few()
    answers = Answer.objects.filter(
        response__window=window,
        response__offering=offering,
        question=question,
        encrypted_text__isnull=False,
    ).only("id", "encrypted_text")
    return [
        Comment(answer.encrypted_text, sentiment_of(answer.encrypted_text))
        for answer in anonymity.stable_shuffle(answers, offering=offering, window=window)
    ]
