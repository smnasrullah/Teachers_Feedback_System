"""Notifications: the in-app inbox, editable message templates, and the delivery bookkeeping.

Nothing here stores message text that was sent, only which kind of message went where."""

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


class Kind(models.TextChoices):
    ROUND_OPENED = "round_opened", _("A feedback round opened")
    CLOSING_SOON = "closing_soon", _("A feedback round closes soon")
    HOD_REMINDER = "hod_reminder", _("A reminder from the head of department")
    RESULTS_AVAILABLE = "results_available", _("Results are available")


class Notification(models.Model):
    """One in-app notice. It keeps the kind and the values to fill in, not the wording: the
    text is rendered from the template in the reader's language each time it is shown."""

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name=_("user"),
    )
    kind = models.CharField(_("kind"), max_length=24, choices=Kind.choices)
    params = models.JSONField(_("values"), default=dict)
    url = models.CharField(_("link"), max_length=200, blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    read_at = models.DateTimeField(_("read at"), null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = _("notification")
        verbose_name_plural = _("notifications")
        indexes = [models.Index(fields=["user", "read_at"], name="notification_user_unread")]

    def __str__(self):
        return f"Notification({self.pk})"


class MessageTemplate(models.Model):
    """The Admin's wording for one kind of message. A blank field means the built-in text."""

    kind = models.CharField(_("kind"), max_length=24, choices=Kind.choices, unique=True)
    subject_en = models.CharField(_("subject (English)"), max_length=200, blank=True)
    subject_bn = models.CharField(_("subject (Bangla)"), max_length=200, blank=True)
    body_en = models.TextField(_("message (English)"), blank=True)
    body_bn = models.TextField(_("message (Bangla)"), blank=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("message template")
        verbose_name_plural = _("message templates")

    def __str__(self):
        return f"MessageTemplate({self.kind})"


class Dispatch(models.Model):
    """Records that a user was sent a scheduled message on a channel, so a repeated run of the
    scheduler sends it once. ``stage`` names the moment: ``opened``, ``h24`` or ``results``."""

    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="dispatches")
    window = models.ForeignKey(
        "feedback.FeedbackWindow", on_delete=models.CASCADE, related_name="dispatches"
    )
    stage = models.CharField(max_length=16)
    channel = models.CharField(max_length=8)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "window", "stage", "channel"], name="one_dispatch_per_stage"
            )
        ]

    def __str__(self):
        return f"Dispatch({self.pk})"


class DeliveryStatus(models.TextChoices):
    SENT = "sent", _("Sent")
    FAILED = "failed", _("Failed")
    SKIPPED = "skipped", _("Skipped")


class DeliveryLog(models.Model):
    """What happened to one outgoing message: kind, channel and outcome, never its content or
    destination. ``detail`` is a short reason code such as ``quiet_hours`` or an exception name."""

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="delivery_logs",
        verbose_name=_("recipient"),
    )
    kind = models.CharField(_("kind"), max_length=24)
    channel = models.CharField(_("channel"), max_length=8)
    status = models.CharField(_("status"), max_length=8, choices=DeliveryStatus.choices)
    detail = models.CharField(_("detail"), max_length=64, blank=True)
    created_at = models.DateTimeField(_("time"), auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = _("delivery log entry")
        verbose_name_plural = _("delivery log")

    def __str__(self):
        return f"DeliveryLog({self.pk})"
