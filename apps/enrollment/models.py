"""Which student takes which offering (points at profiles, never at ``User``: BLUEPRINT §5.1)."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class EnrollmentStatus(models.TextChoices):
    REGULAR = "regular", _("Regular")
    RETAKE = "retake", _("Retake")


class Enrollment(models.Model):
    student_profile = models.ForeignKey(
        "accounts.StudentProfile",
        on_delete=models.PROTECT,
        related_name="enrollments",
        verbose_name=_("student"),
    )
    offering = models.ForeignKey(
        "academics.CourseOffering",
        on_delete=models.PROTECT,
        related_name="enrollments",
        verbose_name=_("course offering"),
    )
    status = models.CharField(
        _("status"),
        max_length=16,
        choices=EnrollmentStatus.choices,
        default=EnrollmentStatus.REGULAR,
    )

    class Meta:
        verbose_name = _("enrollment")
        verbose_name_plural = _("enrollments")
        constraints = [
            models.UniqueConstraint(
                fields=["student_profile", "offering"],
                name="enrollment_unique_pair",
                violation_error_message=_("This student is already enrolled in this offering."),
            )
        ]

    def __str__(self):
        return f"Enrollment({self.pk})"
