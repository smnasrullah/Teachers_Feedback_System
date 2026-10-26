"""Moderation of comments: the Admin approves or hides, a teacher can report; nobody edits.

A comment waits in the queue when the filter cleaned it or a teacher reported it. Approving
keeps it shown, hiding removes it from every report and count of comments. The text is never
changed here, and no decision records who wrote the comment (nobody knows) or when it was
written (nothing stores that). A decision is audited by the answer's random id only.
"""

import hmac
from enum import StrEnum

from django.db import transaction
from django.http import Http404

from apps.auditlog.services import audit
from apps.feedback.models import Answer, FeedbackResponse, ModerationStatus, QuestionType
from apps.feedback.services import anonymity


class Decision(StrEnum):
    APPROVE = "approve"
    HIDE = "hide"


class Filter(StrEnum):
    QUEUE = "queue"
    APPROVED = "approved"
    HIDDEN = "hidden"


_STATUS_OF = {Decision.APPROVE: ModerationStatus.APPROVED, Decision.HIDE: ModerationStatus.HIDDEN}


def comments_in(view: str):
    """The text answers of one tab of the moderation screen, in random-id order (not time)."""
    answers = Answer.objects.filter(encrypted_text__isnull=False).select_related("question")
    if view == Filter.APPROVED:
        answers = answers.filter(moderation=ModerationStatus.APPROVED)
    elif view == Filter.HIDDEN:
        answers = answers.filter(moderation=ModerationStatus.HIDDEN)
    else:
        answers = answers.awaiting_review()
    return answers.order_by("id")


def queue_size() -> int:
    return Answer.objects.filter(encrypted_text__isnull=False).awaiting_review().count()


def decide(answer_id, decision: Decision, *, actor, request=None) -> Answer:
    """Approve or hide one comment. Deciding again later is allowed (hide an approved comment,
    restore a hidden one)."""
    status = _STATUS_OF[decision]
    with transaction.atomic():
        answer = Answer.objects.select_for_update().filter(pk=answer_id).first()
        if answer is None or answer.encrypted_text is None:
            raise Http404
        previous = answer.moderation
        answer.moderation = status
        answer.save(update_fields=["moderation"])
        audit.record(
            f"moderation.{status.value}",
            request=request,
            actor=actor,
            target=answer,
            metadata={"previous": previous},
        )
    return answer


def _find_by_token(token, offering, window):
    """The id of the shown text answer of ``offering`` in ``window`` that ``token`` names."""
    candidates = Answer.objects.shown().filter(
        response__offering=offering,
        response__window=window,
        question__question_type=QuestionType.TEXT,
        encrypted_text__isnull=False,
    )
    for answer_id in candidates.values_list("pk", flat=True):
        if hmac.compare_digest(anonymity.comment_token(answer_id, offering, window), token):
            return answer_id
    raise Http404


def report(token, offering, window, *, actor, request=None) -> bool:
    """A teacher reports a comment on their own offering for the Admin to review.

    ``token`` is the handle the report page gave the comment (``anonymity.comment_token``).
    The comment must be one the teacher can read now (round released, enough responses, not
    hidden). Returns ``False`` when it is already waiting for or past a decision.
    """
    if not anonymity.results_visible(window):
        raise Http404
    if not anonymity.enough_responses(
        FeedbackResponse.objects.filter(offering=offering, window=window).count()
    ):
        raise Http404
    answer_id = _find_by_token(token, offering, window)
    with transaction.atomic():
        answer = Answer.objects.select_for_update().shown().filter(pk=answer_id).first()
        if answer is None:
            raise Http404
        if answer.moderation != ModerationStatus.UNREVIEWED:
            return False
        answer.moderation = ModerationStatus.REPORTED
        answer.save(update_fields=["moderation"])
        audit.record(
            "moderation.reported",
            request=request,
            actor=actor,
            target=answer,
            department_id=offering.course.department_id,
        )
    return True
