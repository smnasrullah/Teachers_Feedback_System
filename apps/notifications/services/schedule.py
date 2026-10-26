"""The scheduled jobs: round reminders, head-of-department reminders, and result notices.

Each job takes ``now`` so a test can set the clock, and is safe to run again: ``Dispatch`` rows
(or the claim on a reminder request) make every message go out once per channel.
"""

from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Exists, OuterRef
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import CourseOffering
from apps.accounts.models import AcademicStatus, RegistryStatus, TeacherProfile, User
from apps.core.services import system_settings
from apps.enrollment.models import Enrollment
from apps.feedback.models import FeedbackWindow, SubmissionReceipt
from apps.feedback.services import anonymity
from apps.notifications.models import Dispatch, Kind, ReminderRequest
from apps.notifications.services import delivery

OPENED = "opened"
RESULTS = "results"
# A closed round older than this is not announced (a fresh install must not announce history).
RESULTS_NOTICE_DAYS = 14


def scoped_offerings(window):
    """Offerings the round covers: its semester, narrowed by its departments and levels/terms."""
    offerings = CourseOffering.objects.filter(semester_id=window.semester_id)
    departments = list(window.departments.values_list("pk", flat=True))
    if departments:
        offerings = offerings.filter(course__department_id__in=departments)
    level_terms = list(window.level_terms.values_list("pk", flat=True))
    if level_terms:
        offerings = offerings.filter(course__level_term_id__in=level_terms)
    return offerings


def pending_counts(window) -> dict[int, int]:
    """Forms each student still owes in ``window``, by the student's user id. A receipt is only
    matched to its own student and offering; it holds nothing else."""
    receipt = SubmissionReceipt.objects.filter(
        window=window,
        offering=OuterRef("offering"),
        student_profile=OuterRef("student_profile"),
    )
    rows = (
        Enrollment.objects.filter(
            offering__in=scoped_offerings(window),
            student_profile__academic_status=AcademicStatus.ACTIVE,
            student_profile__registry__status=RegistryStatus.CLAIMED,
            student_profile__registry__claimed_by__is_active=True,
        )
        .filter(~Exists(receipt))
        .values("student_profile__registry__claimed_by")
        .annotate(forms=Count("pk"))
    )
    return {row["student_profile__registry__claimed_by"]: row["forms"] for row in rows}


def due_stage(window, now) -> tuple[str, str, int | None] | None:
    """The latest reminder moment of an open round that has been reached: ``(stage, kind,
    hours left)``. Earlier moments that were missed are not sent late."""
    if not window.is_open(now):
        return None
    moments = []
    if system_settings.get("REMINDER_ON_OPEN"):
        moments.append((window.opens_at, OPENED, Kind.ROUND_OPENED, None))
    for hours in system_settings.get("REMINDER_HOURS_BEFORE_CLOSE"):
        moment = window.closes_at - timedelta(hours=hours)
        moments.append((moment, f"h{hours}", Kind.CLOSING_SOON, hours))
    reached = [moment for moment in moments if window.opens_at <= moment[0] <= now]
    if not reached:
        return None
    _at, stage, kind, hours = max(reached, key=lambda moment: moment[0])
    return stage, kind, hours


def _settled(window, stage) -> dict[int, set[str]]:
    settled = defaultdict(set)
    rows = Dispatch.objects.filter(window=window, stage=stage).values_list("user_id", "channel")
    for user_id, channel in rows:
        settled[user_id].add(channel)
    return settled


def _send_stage(users, window, stage, kind, params_for, url, now) -> int:
    settled = _settled(window, stage)
    sent = 0
    for user in users:
        channels = delivery.notify(
            user,
            kind,
            params_for(user),
            url=url,
            now=now,
            skip=settled[user.pk],
            quiet=delivery.DEFER,
        )
        Dispatch.objects.bulk_create(
            [Dispatch(user=user, window=window, stage=stage, channel=c) for c in channels],
            ignore_conflicts=True,
        )
        sent += bool(channels)
    return sent


def send_round_reminders(now=None) -> int:
    """Remind every student with an unsubmitted form of each open round at its due moment.
    Returns how many students got something new."""
    now = now or timezone.now()
    total = 0
    windows = FeedbackWindow.objects.filter(is_active=True, opens_at__lte=now, closes_at__gt=now)
    for window in windows:
        due = due_stage(window, now)
        if due is None:
            continue
        stage, kind, hours = due
        counts = pending_counts(window)
        base = {"round": window.name, "closes_at": window.closes_at.isoformat()}
        if hours is not None:
            base["hours"] = hours
        users = User.objects.filter(pk__in=counts, is_active=True)
        total += _send_stage(
            users,
            window,
            stage,
            kind,
            lambda user, counts=counts, base=base: {**base, "pending": counts[user.pk]},
            reverse("accounts:dashboard_student"),
            now,
        )
    return total


def process_reminder_requests(now=None) -> int:
    """Deliver the reminders heads of department queued. A form submitted since, or a round no
    longer open, needs no reminder. Returns how many students were reminded."""
    now = now or timezone.now()
    reminded = 0
    waiting = ReminderRequest.objects.filter(processed_at__isnull=True).select_related(
        "window", "offering__course", "student_profile__registry__claimed_by"
    )
    for request in waiting:
        claimed = ReminderRequest.objects.filter(pk=request.pk, processed_at__isnull=True).update(
            processed_at=now
        )
        user = request.student_profile.registry.claimed_by
        if not claimed or user is None or not user.is_active:
            continue
        submitted = SubmissionReceipt.objects.filter(
            student_profile=request.student_profile,
            offering=request.offering,
            window=request.window,
        ).exists()
        if submitted or not request.window.is_open(now):
            continue
        params = {
            "round": request.window.name,
            "closes_at": request.window.closes_at.isoformat(),
            "course": str(request.offering.course),
        }
        delivery.notify(
            user,
            Kind.HOD_REMINDER,
            params,
            url=reverse("accounts:dashboard_student"),
            now=now,
            quiet=delivery.SKIP,
        )
        reminded += 1
    return reminded


def _result_recipients(window) -> dict[int, str]:
    """Teachers who taught in the round and heads of the departments involved, by user id, each
    with the page their notice links to (a head's overview, else the teacher's courses)."""
    offerings = scoped_offerings(window)
    teachers = TeacherProfile.objects.filter(offerings__in=offerings)
    heads = TeacherProfile.objects.filter(
        is_hod=True, hod_department__in=offerings.values("course__department")
    )
    recipients = {}
    for profiles, url in (
        (teachers, reverse("reports:overview")),
        (heads, reverse("accounts:dashboard_hod")),
    ):
        users = User.objects.filter(is_active=True, registry__in=profiles.values("registry"))
        recipients.update(dict.fromkeys(users.values_list("pk", flat=True), url))
    return recipients


def announce_results(now=None) -> int:
    """Tell teachers and heads once that a closed round's results can be read. Rounds whose
    results the Admin is holding back are announced when they are released. Returns how many
    users got something new."""
    now = now or timezone.now()
    total = 0
    recent = FeedbackWindow.objects.filter(
        closes_at__lte=now, closes_at__gte=now - timedelta(days=RESULTS_NOTICE_DAYS)
    )
    for window in recent:
        if not anonymity.results_visible(window, now):
            continue
        recipients = _result_recipients(window)
        params = {"round": window.name}
        by_url = defaultdict(list)
        for user in User.objects.filter(pk__in=recipients):
            by_url[recipients[user.pk]].append(user)
        for url, users in by_url.items():
            total += _send_stage(
                users,
                window,
                RESULTS,
                Kind.RESULTS_AVAILABLE,
                lambda _user, params=params: params,
                url,
                now,
            )
    return total
