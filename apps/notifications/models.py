"""The reminder queue. P18 turns each waiting request into a delivered notification."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class ReminderRequest(models.Model):
    """A head of department's request to remind one student about one pending feedback form.

    It names the student and the form but holds no feedback and no submission time. A request
    stays waiting (``processed_at`` empty) until the sender handles it, and a second request
    for the same form is ignored meanwhile.
    """

    student_profile = models.ForeignKey(
        "accounts.StudentProfile",
        on_delete=models.CASCADE,
        related_name="reminder_requests",
        verbose_name=_("student"),
    )
    offering = models.ForeignKey(
        "academics.CourseOffering",
        on_delete=models.CASCADE,
        related_name="reminder_requests",
        verbose_name=_("course offering"),
    )
    window = models.ForeignKey(
        "feedback.FeedbackWindow",
        on_delete=models.CASCADE,
        related_name="reminder_requests",
        verbose_name=_("feedback round"),
    )
    requested_at = models.DateTimeField(_("requested at"), auto_now_add=True)
    processed_at = models.DateTimeField(_("processed at"), null=True, blank=True)

    class Meta:
        verbose_name = _("reminder request")
        verbose_name_plural = _("reminder requests")
        constraints = [
            models.UniqueConstraint(
                fields=["student_profile", "offering", "window"],
                condition=models.Q(processed_at__isnull=True),
                name="one_waiting_reminder_per_form",
            )
        ]

    def __str__(self):
        return f"ReminderRequest({self.pk})"
