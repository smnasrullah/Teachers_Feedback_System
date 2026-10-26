"""What a teacher did about one round's results, written for the head of department."""

from django.db import models
from django.utils.translation import gettext_lazy as _

NOTE_MAX_LENGTH = 2000


class ActionNote(models.Model):
    """The "action taken" note of one offering in one round. It is the teacher's own text,
    not feedback, so it may carry the time it was last saved."""

    offering = models.ForeignKey(
        "academics.CourseOffering",
        on_delete=models.CASCADE,
        related_name="action_notes",
        verbose_name=_("course offering"),
    )
    window = models.ForeignKey(
        "feedback.FeedbackWindow",
        on_delete=models.CASCADE,
        related_name="action_notes",
        verbose_name=_("feedback round"),
    )
    text = models.TextField(_("action taken"), max_length=NOTE_MAX_LENGTH)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("action note")
        verbose_name_plural = _("action notes")
        constraints = [
            models.UniqueConstraint(fields=["offering", "window"], name="one_action_note_per_round")
        ]

    def __str__(self):
        return f"ActionNote({self.pk})"
