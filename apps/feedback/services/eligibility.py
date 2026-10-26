"""Whether a student may answer for an offering in a round, decided from the database.

Callers pass objects they were handed; nothing on them is trusted. The window and offering
are re-read, and the enrollment row is locked so a draft save and a submission for the same
course take turns (a draft can never be written back after the submit deleted it).
"""

from enum import StrEnum

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.academics.models import CourseOffering
from apps.enrollment.models import Enrollment
from apps.feedback.models import FeedbackWindow


class Rejection(StrEnum):
    REAUTH_REQUIRED = "reauth_required"
    ALREADY_SUBMITTED = "already_submitted"
    WINDOW_CLOSED = "window_closed"
    OUT_OF_SCOPE = "out_of_scope"
    NOT_ENROLLED = "not_enrolled"


MESSAGES = {
    Rejection.REAUTH_REQUIRED: _("Confirm your password again, then submit."),
    Rejection.ALREADY_SUBMITTED: _(
        "You have already given feedback for this course in this round."
    ),
    Rejection.WINDOW_CLOSED: _("This feedback round is not open."),
    Rejection.OUT_OF_SCOPE: _("This course is not part of this feedback round."),
    Rejection.NOT_ENROLLED: _("You are not enrolled in this course."),
}


class SubmissionRejected(ValidationError):
    """The whole submission (or draft) is refused; ``reason`` says why."""

    def __init__(self, reason: Rejection):
        super().__init__(MESSAGES[reason], code=reason.value)
        self.reason = reason


def check_eligible(student_profile, offering, window) -> tuple[CourseOffering, FeedbackWindow]:
    """Return fresh copies of ``offering`` and ``window`` or raise ``SubmissionRejected``.

    Must run inside a transaction (the enrollment lock lasts until it ends).
    """
    window = FeedbackWindow.objects.get(pk=window.pk)
    if not window.is_open(timezone.now()):
        raise SubmissionRejected(Rejection.WINDOW_CLOSED)
    offering = CourseOffering.objects.select_related("course").get(pk=offering.pk)
    if not window.covers(offering):
        raise SubmissionRejected(Rejection.OUT_OF_SCOPE)
    enrollment = (
        Enrollment.objects.select_for_update()
        .filter(student_profile=student_profile, offering=offering)
        .values_list("pk", flat=True)
        .first()
    )
    if enrollment is None:
        raise SubmissionRejected(Rejection.NOT_ENROLLED)
    return offering, window
