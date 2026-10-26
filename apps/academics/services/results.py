"""Enter and publish the grades of one offering; every save is audited with counts only."""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.academics.models import Result
from apps.auditlog.services import audit
from apps.enrollment.models import Enrollment


@dataclass(frozen=True)
class SaveSummary:
    created: int
    changed: int
    published: int


def grade_sheet(offering):
    """The offering's enrollments with their result, in a stable order."""
    return (
        Enrollment.objects.filter(offering=offering)
        .select_related("result__grade", "student_profile__registry")
        .order_by("pk")
    )


@transaction.atomic
def save_grades(offering, grades: dict, *, publish: bool, actor, request=None) -> SaveSummary:
    """Set ``grades`` ({enrollment pk: GradeScale or None}) on the offering's enrollments.

    ``None`` leaves an enrollment as it is. Publishing releases every result of the offering
    at once, so it needs a grade for every enrolled student.
    """
    enrollments = {
        enrollment.pk: enrollment
        for enrollment in Enrollment.objects.select_for_update()
        .filter(offering=offering)
        .order_by("pk")
    }
    if not set(grades) <= set(enrollments):
        raise ValidationError(_("A grade was given for a student not enrolled in this offering."))
    stored = {
        result.enrollment_id: result
        for result in Result.objects.filter(enrollment_id__in=list(enrollments))
    }
    created, changed = [], []
    for pk, grade in grades.items():
        if grade is None:
            continue
        result = stored.get(pk)
        if result is None:
            created.append(Result(enrollment_id=pk, grade=grade, points=grade.points))
        elif result.grade_id != grade.pk:
            result.grade, result.points = grade, grade.points
            changed.append(result)
    Result.objects.bulk_create(created)
    Result.objects.bulk_update(changed, ["grade", "points"])
    published = 0
    if publish:
        if len(stored) + len(created) < len(enrollments):
            raise ValidationError(
                _(
                    "Every enrolled student needs a grade before the results are published. "
                    "Nothing was saved."
                )
            )
        published = Result.objects.filter(enrollment__offering=offering, published=False).update(
            published=True
        )
    summary = SaveSummary(len(created), len(changed), published)
    if created or changed or published:
        audit.record(
            "results.saved",
            request=request,
            actor=actor,
            target=offering,
            department_id=offering.course.department_id,
            metadata={
                "created": summary.created,
                "changed": summary.changed,
                "published": summary.published,
            },
        )
    return summary
