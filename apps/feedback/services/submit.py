"""Submit one student's feedback for one offering in one round (BLUEPRINT §2 G-K, §5.2).

The receipt is inserted first: its unique constraint is the lock, so of two parallel
submissions exactly one commits and the other is told it already submitted. The response and
its answers are written in the same transaction but carry nothing that points back at the
student, the receipt or the moment of submission. The audit trail records that a student
submitted, never what.
"""

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from apps.analytics import services as analytics
from apps.auditlog.services import audit
from apps.feedback.models import (
    SCALE_MAX,
    SCALE_MIN,
    Answer,
    Draft,
    FeedbackResponse,
    Question,
    QuestionType,
    SubmissionReceipt,
)
from apps.feedback.services import filter as text_filter
from apps.feedback.services.eligibility import Rejection, SubmissionRejected, check_eligible

TEXT_MAX_LENGTH = 2000
YES, NO = "yes", "no"


def submit_feedback(
    student_profile, offering, window, answers: dict, *, reauth_ok: bool, request=None
) -> SubmissionReceipt:
    """Store ``answers`` ({question pk: raw value}) anonymously and return the receipt.

    ``reauth_ok`` is the caller's fresh password re-check (``proxy.reauth_is_fresh``).
    Raises ``SubmissionRejected`` when the submission is refused as a whole (audited) and
    ``ValidationError`` keyed by question pk when answers are missing or invalid.
    """
    actor = student_profile.registry.claimed_by
    department_id = offering.course.department_id
    try:
        if not reauth_ok:
            raise SubmissionRejected(Rejection.REAUTH_REQUIRED)
        with transaction.atomic():
            receipt = _store(student_profile, offering, window, answers)
            transaction.on_commit(lambda: analytics.invalidate(window))
            audit.record(
                "feedback.submitted",
                request=request,
                actor=actor,
                target=offering,
                department_id=department_id,
                metadata={"window_id": window.pk},
            )
    except SubmissionRejected as exc:
        audit.record(
            "feedback.submit_rejected",
            request=request,
            actor=actor,
            target=offering,
            department_id=department_id,
            metadata={"window_id": window.pk, "reason": exc.reason.value},
        )
        raise
    return receipt


def _store(student_profile, offering, window, answers: dict) -> SubmissionReceipt:
    try:
        with transaction.atomic():
            receipt = SubmissionReceipt.objects.create(
                student_profile=student_profile, offering=offering, window=window
            )
    except IntegrityError as exc:
        raise SubmissionRejected(Rejection.ALREADY_SUBMITTED) from exc
    offering, window = check_eligible(student_profile, offering, window)
    rows = clean_answers(Question.objects.for_offering(offering), answers)
    response = FeedbackResponse.objects.create(offering=offering, window=window)
    Answer.objects.bulk_create(Answer(response=response, **row) for row in rows)
    Draft.objects.filter(student_profile=student_profile, offering=offering, window=window).delete()
    return receipt


def clean_answers(questions, answers: dict) -> list[dict]:
    """Validate ``answers`` against the offering's ``questions``; return the Answer values.

    Unanswered optional questions and optional comments that the filter empties store
    nothing. Errors are collected for every question before raising.
    """
    by_pk = {question.pk: question for question in questions}
    if not set(answers) <= set(by_pk):
        raise ValidationError(
            {
                NON_FIELD_ERRORS: ValidationError(
                    _(
                        "The questions changed after this form was opened. "
                        "Reload the page and answer again."
                    ),
                    code="stale_form",
                )
            }
        )
    rows, errors = [], {}
    for pk, question in by_pk.items():
        try:
            values = _clean_one(question, answers.get(pk))
        except ValidationError as exc:
            errors[pk] = exc
            continue
        if values is not None:
            rows.append({"question": question, **values})
    if errors:
        raise ValidationError(errors)
    return rows


def _clean_one(question: Question, raw) -> dict | None:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if question.required:
            raise ValidationError(_("This question needs an answer."), code="required")
        return None
    match question.question_type:
        case QuestionType.RATING | QuestionType.LIKERT:
            value = _as_int(raw)
            if value is None or not SCALE_MIN <= value <= SCALE_MAX:
                raise ValidationError(
                    _("Choose a value from %(low)d to %(high)d."),
                    code="out_of_range",
                    params={"low": SCALE_MIN, "high": SCALE_MAX},
                )
            return {"int_value": value}
        case QuestionType.YES_NO:
            value = (YES if raw else NO) if isinstance(raw, bool) else str(raw).strip().lower()
            if value not in (YES, NO):
                raise ValidationError(_("Answer yes or no."), code="invalid_choice")
            return {"choice_value": value}
        case QuestionType.CHOICE:
            value = raw.strip() if isinstance(raw, str) else None
            if value not in question.option_values():
                raise ValidationError(_("Choose one of the options."), code="invalid_choice")
            return {"choice_value": value}
        case QuestionType.TEXT:
            return _clean_text(question, raw)
    raise ValidationError(_("This question cannot be answered."), code="unknown_type")


def _as_int(raw) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.strip().isdecimal():
        return int(raw.strip())
    return None


def _clean_text(question: Question, raw) -> dict | None:
    if not isinstance(raw, str):
        raise ValidationError(_("Enter text."), code="invalid")
    text = raw.strip()
    if len(text) > TEXT_MAX_LENGTH:
        raise ValidationError(
            _("Keep the answer under %(limit)d characters."),
            code="max_length",
            params={"limit": TEXT_MAX_LENGTH},
        )
    result = text_filter.clean(text)
    if result.empty:
        if question.required:
            message = _("Nothing was left of this answer after it was cleaned. Please rewrite it.")
            raise ValidationError(" ".join([message, *result.messages()]), code="cleaned_empty")
        return None
    return {"encrypted_text": result.text, "flagged": result.flagged}
