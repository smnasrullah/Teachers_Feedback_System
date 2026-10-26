"""Drafts of an unfinished form: encrypted, owner-only, gone once submitted (BLUEPRINT §5.2 A6).

A draft keeps the raw answers exactly as typed; nothing in it is validated or filtered
until ``submit_feedback`` runs.
"""

import json

from django.db import transaction

from apps.feedback.models import Draft, Question, SubmissionReceipt
from apps.feedback.services.eligibility import Rejection, SubmissionRejected, check_eligible
from apps.feedback.services.submit import TEXT_MAX_LENGTH


def _keepable(value) -> bool:
    if isinstance(value, str):
        return len(value) <= TEXT_MAX_LENGTH
    return value is None or isinstance(value, bool | int)


@transaction.atomic
def save_draft(student_profile, offering, window, answers: dict) -> Draft:
    """Store ``answers`` ({question pk: raw value}) for the student's own form.

    Answers to questions not on the form and values a form cannot produce are dropped.
    Refused like a submission once submitted, outside the open round or when not enrolled.
    """
    offering, window = check_eligible(student_profile, offering, window)
    if SubmissionReceipt.objects.filter(
        student_profile=student_profile, offering=offering, window=window
    ).exists():
        raise SubmissionRejected(Rejection.ALREADY_SUBMITTED)
    on_form = set(Question.objects.for_offering(offering).values_list("pk", flat=True))
    kept = {str(pk): value for pk, value in answers.items() if pk in on_form and _keepable(value)}
    draft, _ = Draft.objects.update_or_create(
        student_profile=student_profile,
        offering=offering,
        window=window,
        defaults={"payload": json.dumps(kept, ensure_ascii=False)},
    )
    return draft


def load_draft(student_profile, offering, window) -> dict:
    """The student's saved answers ({question pk: raw value}), empty when there is none."""
    payload = (
        Draft.objects.filter(student_profile=student_profile, offering=offering, window=window)
        .values_list("payload", flat=True)
        .first()
    )
    return {int(pk): value for pk, value in json.loads(payload).items()} if payload else {}
