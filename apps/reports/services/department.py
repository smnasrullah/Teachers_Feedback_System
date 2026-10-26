"""What a head of department sees of their own department (BLUEPRINT §4, §5.3).

Scope is every offering whose course belongs to the department. Figures come from
``apps.analytics`` through ``teacher.summarize``, so a round still open and a group below the
response threshold show no number here either. Each ranked row stands on its own offering: a
teacher's offerings are never merged, because a merged figure could be subtracted from the
published ones to expose a hidden group.

The pending list works from receipts and enrolments only. It lists a student with the ID only
when ``StudentIdPolicy`` allows it (own department); students of other departments in a service
course are counted, never listed. Nothing in this module can reach who wrote an answer.
"""

import math
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Exists, OuterRef, Prefetch
from django.utils import timezone

from apps.academics.models import CourseOffering, LevelTerm
from apps.accounts.models import StudentProfile
from apps.accounts.services.student_id_policy import with_visible_ids
from apps.analytics import services as analytics
from apps.analytics.services import InsufficientData
from apps.auditlog.models import AuditEvent
from apps.auditlog.services import audit
from apps.core.permissions import Role
from apps.core.services import system_settings
from apps.core.services.localize import pick
from apps.enrollment.models import Enrollment
from apps.feedback.models import FeedbackWindow, SubmissionReceipt
from apps.notifications import tasks
from apps.notifications.models import ReminderRequest
from apps.reports.models import ActionNote
from apps.reports.services import teacher
from apps.reports.services.teacher import CourseSummary

THRESHOLD_MIN = 1.0
THRESHOLD_MAX = 5.0
HEAT_LEVELS = 5


class RemindersClosed(Exception):
    """Reminders are only worth sending while the round is open."""


@dataclass(frozen=True)
class Row:
    summary: CourseSummary
    note: ActionNote | None
    rank: int | None = None
    low: bool = False

    @property
    def offering(self) -> CourseOffering:
        return self.summary.offering


@dataclass(frozen=True)
class HeatCell:
    score: float
    level: int


@dataclass(frozen=True)
class HeatRow:
    summary: CourseSummary
    cells: tuple[HeatCell | None, ...]


@dataclass(frozen=True)
class Heatmap:
    categories: tuple[str, ...]
    rows: tuple[HeatRow, ...]


@dataclass(frozen=True)
class Overview:
    window: FeedbackWindow
    threshold: float
    rows: tuple[Row, ...]
    offerings: int
    teachers: int
    rate: analytics.ResponseRate | InsufficientData | None
    average: analytics.DepartmentAverage | InsufficientData
    heatmap: Heatmap
    trend: dict | None
    trend_summary: str

    @property
    def alerts(self) -> tuple[Row, ...]:
        return tuple(sorted((row for row in self.rows if row.low), key=lambda r: r.summary.average))

    @property
    def noted(self) -> tuple[Row, ...]:
        return tuple(row for row in self.rows if row.note)


@dataclass(frozen=True)
class PendingRow:
    student: StudentProfile
    offering: CourseOffering


@dataclass(frozen=True)
class PendingList:
    rows: tuple[PendingRow, ...]
    others: int


# --- scope -----------------------------------------------------------------------------------


def threshold_from(raw) -> float:
    """The alert threshold asked for, kept within the rating scale; the setting otherwise."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return system_settings.get("LOW_RATING_THRESHOLD")
    if not math.isfinite(value):
        return system_settings.get("LOW_RATING_THRESHOLD")
    return min(max(value, THRESHOLD_MIN), THRESHOLD_MAX)


def department_offerings(department):
    return CourseOffering.objects.filter(course__department=department)


def rounds(department, now) -> list[FeedbackWindow]:
    return teacher.rounds_covering(department_offerings(department), now)


def pick_pending_round(available, requested_id, now) -> FeedbackWindow | None:
    """The requested round, else an open one (reminders matter most then), else the usual pick."""
    by_id = {window.pk: window for window in available}
    if requested_id in by_id:
        return by_id[requested_id]
    open_now = [window for window in available if window.is_open(now)]
    return open_now[0] if open_now else teacher.pick_round(available, None, now)


def offerings_in_scope(department, window) -> list[CourseOffering]:
    offerings = (
        department_offerings(department)
        .filter(semester=window.semester)
        .select_related("course", "semester", "teacher__registry")
        .order_by("course__code", "section")
    )
    return [offering for offering in offerings if window.covers(offering)]


def offering_in_scope(department, window, offering_id) -> CourseOffering:
    """One offering of the department in ``window``; anything else is refused."""
    for offering in offerings_in_scope(department, window):
        if offering.pk == offering_id:
            return offering
    raise PermissionDenied


# --- overview --------------------------------------------------------------------------------


def _rows(summaries, notes, threshold) -> tuple[Row, ...]:
    ranked = sorted(
        (s for s in summaries if s.average is not None),
        key=lambda s: (-s.average, s.offering.course.code, s.offering.section),
    )
    waiting = [s for s in summaries if s.average is None]
    rows = [
        Row(s, notes.get(s.offering.pk), rank, s.average < threshold)
        for rank, s in enumerate(ranked, start=1)
    ]
    rows += [Row(s, notes.get(s.offering.pk)) for s in waiting]
    return tuple(rows)


def _level(score: float) -> int:
    return min(max(round(score), 1), HEAT_LEVELS)


def _heatmap(rows, window, viewer, now) -> Heatmap:
    scored = []
    names: dict[int, str] = {}
    for row in rows:
        if row.rank is None:
            continue
        scores = analytics.category_scores(window, row.offering, viewer=viewer, now=now)
        if isinstance(scores, InsufficientData):
            continue
        usable = {
            pk: score for pk, score in scores.items() if not isinstance(score, InsufficientData)
        }
        for pk, score in usable.items():
            names.setdefault(pk, pick(score.name, score.name_bn))
        scored.append((row.summary, usable))
    heat_rows = tuple(
        HeatRow(
            summary,
            tuple(
                HeatCell(usable[pk].average, _level(usable[pk].average)) if pk in usable else None
                for pk in names
            ),
        )
        for summary, usable in scored
    )
    return Heatmap(tuple(names.values()), heat_rows)


def build_overview(department, window, viewer, now, threshold) -> Overview:
    offerings = offerings_in_scope(department, window)
    summaries = [teacher.summarize(offering, window, viewer, now) for offering in offerings]
    notes = {
        note.offering_id: note
        for note in ActionNote.objects.filter(window=window, offering__in=offerings)
    }
    rows = _rows(summaries, notes, threshold)
    trend = teacher.trend_chart(analytics.trend(department=department, viewer=viewer, now=now))
    return Overview(
        window=window,
        threshold=threshold,
        rows=rows,
        offerings=len(offerings),
        teachers=len({offering.teacher_id for offering in offerings}),
        rate=analytics.response_rate(window, offerings, viewer=viewer, now=now)
        if offerings
        else None,
        average=analytics.department_average(window, department, viewer=viewer, now=now),
        heatmap=_heatmap(rows, window, viewer, now),
        trend=trend,
        trend_summary=teacher.chart_summary(trend),
    )


# --- pending submissions and reminders --------------------------------------------------------


def level_terms():
    return LevelTerm.objects.order_by("order", "name")


def _pending_enrollments(window, offerings, level_term=None):
    """Enrolments in ``offerings`` with no receipt in ``window``. A receipt is only matched to
    its own (student, offering); it holds no content to read."""
    receipt = SubmissionReceipt.objects.filter(
        window=window,
        offering=OuterRef("offering"),
        student_profile=OuterRef("student_profile"),
    )
    pending = Enrollment.objects.filter(offering__in=offerings).filter(~Exists(receipt))
    if level_term is not None:
        pending = pending.filter(student_profile__level_term=level_term)
    return pending


def pending_list(department, window, viewer, offerings, level_term=None) -> PendingList:
    """Own-department students still owing feedback, with their IDs as the policy allows, and
    the number of other-department students (counted, never listed)."""
    pending = _pending_enrollments(window, offerings, level_term)
    students = with_visible_ids(StudentProfile.objects.select_related("level_term"), viewer)
    enrollments = (
        pending.filter(student_profile__registry__department=department)
        .select_related("offering__course")
        .prefetch_related(Prefetch("student_profile", queryset=students))
    )
    rows = sorted(
        (PendingRow(e.student_profile, e.offering) for e in enrollments),
        key=lambda r: (
            r.offering.course.code,
            r.offering.section,
            r.student.visible_student_id or "",
        ),
    )
    others = pending.exclude(student_profile__registry__department=department).count()
    return PendingList(tuple(rows), others)


def queue_reminders(request, department, window, offering, student_id=None, now=None) -> int:
    """Queue a reminder for one pending student of ``offering``, or for all of them.

    A named student must belong to the department, the only ones the head can see. The bulk
    form reaches every pending student, other departments included, without listing anyone.
    Returns how many requests were queued; a form already waiting for a reminder is skipped.
    """
    now = now or timezone.now()
    if offering.course.department_id != department.pk or not window.covers(offering):
        raise PermissionDenied
    if not window.is_open(now):
        raise RemindersClosed
    pending = _pending_enrollments(window, [offering])
    if student_id is not None:
        pending = pending.filter(student_profile_id=student_id)
        if not pending.filter(student_profile__registry__department=department).exists():
            raise PermissionDenied
    waiting = ReminderRequest.objects.filter(
        window=window, offering=offering, processed_at__isnull=True
    )
    with transaction.atomic():
        before = waiting.count()
        ReminderRequest.objects.bulk_create(
            [
                ReminderRequest(student_profile_id=student, offering=offering, window=window)
                for student in pending.values_list("student_profile_id", flat=True)
            ],
            ignore_conflicts=True,
        )
        queued = waiting.count() - before
        audit.record(
            "hod.reminder_queued",
            request=request,
            target=offering,
            department_id=department.pk,
            metadata={"count": queued, "window_id": window.pk},
        )
        if queued:
            transaction.on_commit(tasks.process_reminder_requests.delay)
    return queued


# --- audit ------------------------------------------------------------------------------------


def audit_events(department):
    """Events recorded for the department. Students' own actions (sign-in, submitting) are left
    out: the head reads what staff did, not when a given student acted."""
    return AuditEvent.objects.filter(department_id=department.pk).exclude(
        actor_role=Role.STUDENT.value
    )
