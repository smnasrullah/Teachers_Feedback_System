"""A few in-app notifications per demo account, sent through the normal delivery service."""

from django.urls import reverse
from django.utils import timezone

from apps.core.services.demo.people import Cast
from apps.notifications.models import Kind, Notification
from apps.notifications.services import delivery, inbox

CLOSING_SOON_HOURS = 72


def send_all(cast: Cast, closed, open_, course_label: str, pending: int) -> None:
    """Give each demo account its notices (once: an account that has any is left alone)."""
    now = timezone.now()
    opened = {
        "round": open_.name,
        "closes_at": open_.closes_at.isoformat(),
        "pending": pending,
    }
    closing = {**opened, "hours": CLOSING_SOON_HOURS}
    results = {"round": closed.name}
    reminder = {**opened, "course": course_label}
    student_home = reverse("accounts:dashboard_student")
    plan = (
        (
            cast.student,
            (
                (Kind.ROUND_OPENED, opened, student_home),
                (Kind.CLOSING_SOON, closing, student_home),
                (Kind.HOD_REMINDER, reminder, student_home),
            ),
        ),
        (
            cast.hod,
            (
                (Kind.RESULTS_AVAILABLE, results, reverse("reports:overview")),
                (Kind.ROUND_OPENED, opened, reverse("accounts:dashboard_hod")),
            ),
        ),
        (
            cast.admin,
            (
                (Kind.RESULTS_AVAILABLE, results, reverse("accounts:dashboard_admin")),
                (Kind.ROUND_OPENED, opened, reverse("accounts:dashboard_admin")),
                (Kind.CLOSING_SOON, closing, reverse("accounts:dashboard_admin")),
            ),
        ),
    )
    for user, notices in plan:
        if Notification.objects.filter(user=user).exists():
            continue
        for kind, params, url in notices:
            delivery.notify(user, kind, params, url=url, now=now, quiet=delivery.SKIP)
        oldest = Notification.objects.filter(user=user).order_by("created_at", "pk").first()
        inbox.mark_read(user, oldest.pk)
