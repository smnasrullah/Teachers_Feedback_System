"""Feedback rounds: the no-overlap rule and audited saves.

Status is computed from the datetimes (``FeedbackWindow.status``); nothing here or in the
background jobs ever flips a stored state.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.academics.models import Semester
from apps.analytics import services as analytics
from apps.auditlog.services import audit
from apps.feedback.models import FeedbackWindow


def _overlaps(first: set, second: set) -> bool:
    """Two scopes meet when either is unrestricted (empty) or they share a member."""
    return not first or not second or not first.isdisjoint(second)


def find_overlapping(
    semester, opens_at, closes_at, department_ids, level_term_ids, *, exclude_pk=None
) -> list[FeedbackWindow]:
    """Active rounds of ``semester`` that run at the same time for some of the same courses.

    Rounds that merely touch (one closes at the instant the other opens) do not overlap.
    """
    candidates = (
        FeedbackWindow.objects.filter(
            semester=semester, is_active=True, opens_at__lt=closes_at, closes_at__gt=opens_at
        )
        .exclude(pk=exclude_pk)
        .prefetch_related("departments", "level_terms")
    )
    return [
        window
        for window in candidates
        if _overlaps(department_ids, {d.pk for d in window.departments.all()})
        and _overlaps(level_term_ids, {t.pk for t in window.level_terms.all()})
    ]


def ensure_no_overlap(data: dict, *, exclude_pk=None) -> None:
    clashes = find_overlapping(
        data["semester"],
        data["opens_at"],
        data["closes_at"],
        {d.pk for d in data["departments"]},
        {t.pk for t in data["level_terms"]},
        exclude_pk=exclude_pk,
    )
    if clashes:
        raise ValidationError(
            _("This round overlaps with %(names)s for the same courses."),
            code="overlap",
            params={"names": ", ".join(window.name for window in clashes)},
        )


@transaction.atomic
def save_window(form, *, actor, request=None) -> FeedbackWindow:
    """Save a validated window form and audit it.

    The semester row is locked while the overlap rule is checked again, so two admins
    cannot save clashing rounds at the same moment. Raises ``ValidationError`` on a clash.
    """
    created = form.instance.pk is None
    changed = [] if created else sorted(set(form.changed_data) & set(form._meta.fields))
    if not created and not changed:
        return form.instance
    data = form.cleaned_data
    Semester.objects.select_for_update().get(pk=data["semester"].pk)
    if data["is_active"] and not form.is_locked:
        ensure_no_overlap(data, exclude_pk=form.instance.pk)
    window = form.save()
    transaction.on_commit(lambda: analytics.invalidate(window))
    audit.record(
        f"feedback.window_{'created' if created else 'updated'}",
        request=request,
        actor=actor,
        target=window,
        metadata={"changed": changed},
    )
    return window
