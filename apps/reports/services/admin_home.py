"""What the Admin sees first: people, the running round, participation, the moderation queue,
the latest audit events and two charts. Participation counts receipts and enrolments only; the
rating charts follow the same release rule as every other result."""

from dataclasses import dataclass

from django.db.models import Count
from django.utils import timezone

from apps.academics.models import Department
from apps.accounts.models import User
from apps.analytics import services as analytics
from apps.analytics.services import InsufficientData
from apps.auditlog.models import AuditEvent
from apps.core.permissions import Role
from apps.feedback.models import Answer, FeedbackWindow
from apps.feedback.services import review
from apps.reports.services import teacher, university

RECENT_EVENTS = 6
QUEUE_PREVIEW = 3
GOOD_RATE = 70
LOW_RATE = 60


@dataclass(frozen=True)
class People:
    students: int
    teachers: int
    admins: int

    @property
    def total(self) -> int:
        return self.students + self.teachers + self.admins


@dataclass(frozen=True)
class ParticipationRow:
    department: Department
    percent: float
    tone: str


@dataclass(frozen=True)
class Home:
    people: People
    window: FeedbackWindow | None
    open_now: bool
    rate: analytics.ResponseRate | InsufficientData | None
    departments: tuple[ParticipationRow, ...]
    queue_size: int
    queue_preview: tuple[Answer, ...]
    events: tuple[AuditEvent, ...]
    trend: dict | None
    trend_summary: str
    distribution: dict | None


def people() -> People:
    counts = dict(User.objects.filter(is_active=True).values_list("role").annotate(n=Count("pk")))
    return People(
        counts.get(Role.STUDENT, 0), counts.get(Role.TEACHER, 0), counts.get(Role.ADMIN, 0)
    )


def current_round(now) -> FeedbackWindow | None:
    """The round open now (newest first), else the newest closed one."""
    available = university.rounds(None, now)
    open_now = [window for window in available if window.is_open(now)]
    return open_now[0] if open_now else teacher.pick_round(available, None, now)


def _tone(percent: float) -> str:
    if percent >= GOOD_RATE:
        return "good"
    return "warn" if percent < LOW_RATE else ""


def _participation(window, viewer, now):
    offerings = university.offerings_in_scope(window)
    by_department: dict[Department, list] = {}
    for offering in offerings:
        by_department.setdefault(offering.course.department, []).append(offering)
    rows = []
    for department, group in sorted(by_department.items(), key=lambda item: item[0].code):
        rate = analytics.response_rate(window, group, viewer=viewer, live=True, now=now)
        if not isinstance(rate, InsufficientData):
            rows.append(ParticipationRow(department, rate.percent, _tone(rate.percent)))
    overall = (
        analytics.response_rate(window, offerings, viewer=viewer, live=True, now=now)
        if offerings
        else None
    )
    return overall, tuple(rows)


def build(viewer, now=None) -> Home:
    now = now or timezone.now()
    window = current_round(now)
    rate, rows, distribution = None, (), None
    if window:
        rate, rows = _participation(window, viewer, now)
        distribution = university.distribution_chart(
            analytics.rating_distribution(
                window, university.offerings_in_scope(window), viewer=viewer, now=now
            )
        )
    trend = teacher.trend_chart(analytics.trend(university=True, viewer=viewer, now=now))
    return Home(
        people=people(),
        window=window,
        open_now=bool(window and window.is_open(now)),
        rate=rate,
        departments=rows,
        queue_size=review.queue_size(),
        queue_preview=tuple(review.comments_in(review.Filter.QUEUE)[:QUEUE_PREVIEW]),
        events=tuple(
            AuditEvent.objects.exclude(actor_role=Role.STUDENT.value).order_by(
                "-created_at", "-pk"
            )[:RECENT_EVENTS]
        ),
        trend=trend,
        trend_summary=teacher.chart_summary(trend),
        distribution=distribution,
    )
