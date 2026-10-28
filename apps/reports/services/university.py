"""University-wide analytics for the Admin (BLUEPRINT §4).

One round at a time, narrowed by department and level/term. Ratings, distributions and
rankings come from ``apps.analytics`` for released rounds only (an open round shows participation
and nothing else), and each figure keeps the response threshold. Participation counts receipts
and enrolments, never answers, as it does for the head of department's pending list.
"""

from dataclasses import dataclass

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.academics.models import CourseOffering, Department, LevelTerm, Semester
from apps.analytics import services as analytics
from apps.analytics.services import InsufficientData
from apps.feedback.models import SCALE_MAX, FeedbackWindow
from apps.feedback.services import anonymity
from apps.reports.services import teacher
from apps.reports.services.teacher import CourseSummary

RANKED = 5


@dataclass(frozen=True)
class Filters:
    semester: Semester | None = None
    department: Department | None = None
    level_term: LevelTerm | None = None
    window: FeedbackWindow | None = None


@dataclass(frozen=True)
class DepartmentRow:
    department: Department
    courses: int
    rate: analytics.ResponseRate | InsufficientData
    average: float | None


@dataclass(frozen=True)
class UniversityReport:
    window: FeedbackWindow
    courses: int
    released: bool
    rate: analytics.ResponseRate | InsufficientData
    distribution: tuple[analytics.Bucket, ...] | InsufficientData
    departments: tuple[DepartmentRow, ...]
    top: tuple[CourseSummary, ...]
    bottom: tuple[CourseSummary, ...]
    trend: dict | None
    trend_summary: str


def rounds(semester, now) -> list[FeedbackWindow]:
    """Started, active rounds (of ``semester`` when given), newest first."""
    windows = FeedbackWindow.objects.filter(is_active=True, opens_at__lte=now).select_related(
        "semester"
    )
    if semester is not None:
        windows = windows.filter(semester=semester)
    return list(windows.prefetch_related("departments", "level_terms"))


def pick_round(available, requested, now) -> FeedbackWindow | None:
    """The requested round, else the newest closed one, else the newest."""
    return teacher.pick_round(available, requested.pk if requested else None, now)


def offerings_in_scope(window, department=None, level_term=None) -> list[CourseOffering]:
    offerings = CourseOffering.objects.filter(semester=window.semester).select_related(
        "course__department", "semester", "teacher__registry"
    )
    if department is not None:
        offerings = offerings.filter(course__department=department)
    if level_term is not None:
        offerings = offerings.filter(course__level_term=level_term)
    return [
        offering
        for offering in offerings.order_by("course__code", "section")
        if window.covers(offering)
    ]


def _average(window, offerings, viewer, now) -> float | None:
    stats = analytics.question_stats(window, offerings, viewer=viewer, now=now)
    return None if isinstance(stats, InsufficientData) else teacher.overall_average(stats)


def _department_rows(window, offerings, viewer, now) -> tuple[DepartmentRow, ...]:
    by_department: dict[Department, list[CourseOffering]] = {}
    for offering in offerings:
        by_department.setdefault(offering.course.department, []).append(offering)
    return tuple(
        DepartmentRow(
            department,
            len(group),
            analytics.response_rate(window, group, viewer=viewer, live=True, now=now),
            _average(window, group, viewer, now),
        )
        for department, group in sorted(by_department.items(), key=lambda item: item[0].code)
    )


def _ranking(summaries) -> tuple[tuple[CourseSummary, ...], tuple[CourseSummary, ...]]:
    """The best and the worst courses; a course never appears in both lists."""
    ranked = sorted(
        (s for s in summaries if s.average is not None),
        key=lambda s: (-s.average, s.offering.course.code, s.offering.section),
    )
    top = ranked[:RANKED]
    bottom = list(reversed(ranked[RANKED:]))[:RANKED]
    return tuple(top), tuple(bottom)


def distribution_chart(buckets) -> dict | None:
    if isinstance(buckets, InsufficientData) or not any(bucket.count for bucket in buckets):
        return None
    return {
        "type": "bar",
        "labels": [str(bucket.value) for bucket in buckets],
        "datasets": [
            {
                "label": _("Share of answers (%)"),
                "data": [bucket.percent for bucket in buckets],
                "color": "primary",
            }
        ],
        "scale": {"min": 0, "max": 100},
    }


def department_chart(rows) -> dict | None:
    scored = [row for row in rows if row.average is not None]
    if not scored:
        return None
    return {
        "type": "bar",
        "labels": [row.department.code for row in scored],
        "datasets": [
            {
                "label": _("Average rating"),
                "data": [row.average for row in scored],
                "color": "primary",
            }
        ],
        "scale": {"min": 0, "max": SCALE_MAX},
    }


def build(filters: Filters, viewer, now=None) -> UniversityReport:
    now = now or timezone.now()
    window = filters.window
    offerings = offerings_in_scope(window, filters.department, filters.level_term)
    summaries = [teacher.summarize(offering, window, viewer, now) for offering in offerings]
    top, bottom = _ranking(summaries)
    trend = teacher.trend_chart(
        analytics.trend(
            department=filters.department,
            level_term=filters.level_term,
            university=True,
            viewer=viewer,
            now=now,
        )
    )
    return UniversityReport(
        window=window,
        courses=len(offerings),
        released=anonymity.results_visible(window, now),
        rate=analytics.response_rate(window, offerings, viewer=viewer, live=True, now=now),
        distribution=analytics.rating_distribution(window, offerings, viewer=viewer, now=now),
        departments=_department_rows(window, offerings, viewer, now),
        top=top,
        bottom=bottom,
        trend=trend,
        trend_summary=teacher.chart_summary(trend),
    )
