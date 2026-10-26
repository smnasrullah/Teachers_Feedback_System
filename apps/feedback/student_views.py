"""The student's side: dashboard, feedback form, draft autosave, text pre-check, thank-you.

Every view is for students only, and every course/round pair is looked up through the
student's own enrollments, so anything else answers 404 whether it exists or not.
"""

from datetime import datetime

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django_ratelimit.decorators import ratelimit

from apps.accounts.services import student_id_policy
from apps.core.permissions import Role, role_required
from apps.core.services import sessions
from apps.feedback.models import QuestionType, SubmissionReceipt
from apps.feedback.services import drafts, portal, proxy
from apps.feedback.services import filter as text_filter
from apps.feedback.services.eligibility import SubmissionRejected
from apps.feedback.services.portal import FormState
from apps.feedback.services.proxy import ReauthOutcome
from apps.feedback.services.submit import TEXT_MAX_LENGTH, submit_feedback

STUDENT = Role.STUDENT
HELPER_RATE = "240/10m"
REAUTH_FAILURES = {
    ReauthOutcome.REJECTED: (400, _("The password is not correct. Your answers are still here.")),
    ReauthOutcome.LOCKED: (
        429,
        _("Too many wrong passwords. Please wait a few minutes before you try again."),
    ),
    ReauthOutcome.THROTTLED: (
        429,
        _("Too many attempts. Please wait a few minutes and try again."),
    ),
}


def _profile(request):
    profile = request.user.student_profile
    if profile is None:
        raise PermissionDenied
    return profile


def _target(request, window_id, offering_id):
    profile = _profile(request)
    target = portal.find_target(profile, window_id, offering_id)
    if target is None:
        raise Http404
    return profile, *target


@require_GET
@role_required(STUDENT)
def dashboard(request):
    profile = _profile(request)
    replaced_at = sessions.pop_replaced_device(request)
    context = {
        "profile": profile,
        "dashboard": portal.build_dashboard(profile, timezone.now()),
        "own_id": student_id_policy.own_id_for_display(request.user, profile),
        "replaced_device_at": (
            datetime.fromtimestamp(replaced_at, timezone.get_current_timezone())
            if replaced_at
            else None
        ),
    }
    return render(request, "student/dashboard.html", context)


def _state_page(request, offering, window, state, *, status=200):
    context = {"offering": offering, "window": window, "state": state}
    return render(request, "student/state.html", context, status=status)


def _form_page(
    request,
    offering,
    window,
    questions,
    values,
    *,
    errors=None,
    notices=(),
    reopen=False,
    status=200,
):
    context = {
        "offering": offering,
        "window": window,
        "sections": portal.form_sections(questions, values, errors or {}),
        "fingerprint": portal.fingerprint(questions),
        "required_total": sum(question.required for question in questions),
        "notices": list(notices),
        "reopen_confirm": reopen,
    }
    return render(request, "student/form.html", context, status=status)


@require_http_methods(["GET", "POST"])
@role_required(STUDENT)
def feedback_form(request, window_id, offering_id):
    profile, offering, window = _target(request, window_id, offering_id)
    state = portal.form_state(profile, offering, window, timezone.now())
    posting = request.method == "POST"
    if state != FormState.OPEN:
        return _state_page(request, offering, window, state, status=409 if posting else 200)
    questions = portal.form_questions(offering)
    if not posting:
        values = portal.draft_values(profile, offering, window)
        return _form_page(request, offering, window, questions, values)
    return _submit(request, profile, offering, window, questions)


def _submit(request, profile, offering, window, questions):
    answers = portal.parse_answers(questions, request.POST)

    def again(status, *, errors=None, notices=(), reopen=False):
        return _form_page(
            request,
            offering,
            window,
            questions,
            answers,
            errors=errors,
            notices=notices,
            reopen=reopen,
            status=status,
        )

    if proxy.submit_throttled(request):
        return again(
            429, notices=[_("Too many attempts. Please wait a few minutes and try again.")]
        )
    if request.POST.get("qset") != portal.fingerprint(questions):
        notice = _("The questions changed while you were answering. Please check your answers.")
        return again(409, notices=[notice])
    outcome = proxy.reauthenticate(request, request.POST.get("password", ""))
    if outcome != ReauthOutcome.OK:
        status, notice = REAUTH_FAILURES[outcome]
        return again(status, notices=[notice], reopen=True)
    try:
        submit_feedback(
            profile,
            offering,
            window,
            answers,
            reauth_ok=proxy.reauth_is_fresh(request),
            request=request,
        )
    except SubmissionRejected:
        state = portal.form_state(profile, offering, window, timezone.now())
        if state == FormState.OPEN:
            raise Http404 from None
        return _state_page(request, offering, window, state, status=409)
    except ValidationError as error:
        by_question, general = portal.error_messages(error)
        return again(400, errors=by_question, notices=general)
    return redirect("feedback:done", window_id=window.pk, offering_id=offering.pk)


def _status_fragment(request, message="", *, failed=False, status=200):
    context = {"message": message, "failed": failed}
    return render(request, "student/_draft_status.html", context, status=status)


@require_POST
@role_required(STUDENT)
@ratelimit(key="user", rate=HELPER_RATE, method="POST", block=False)
def draft(request, window_id, offering_id):
    profile, offering, window = _target(request, window_id, offering_id)
    if request.limited:
        return _status_fragment(
            request, _("Saving too often. Wait a moment."), failed=True, status=429
        )
    answers = portal.parse_answers(portal.form_questions(offering), request.POST)
    try:
        drafts.save_draft(profile, offering, window, answers)
    except SubmissionRejected as rejected:
        return _status_fragment(request, rejected.message, failed=True)
    return _status_fragment(request, _("Draft saved"))


@require_POST
@role_required(STUDENT)
@ratelimit(key="user", rate=HELPER_RATE, method="POST", block=False)
def precheck(request, window_id, offering_id, question_id):
    """Tell the student what the filter would take out of a comment before they submit."""
    _student, offering, _window = _target(request, window_id, offering_id)
    if request.limited:
        return render(request, "student/_precheck.html", {"limited": True}, status=429)
    question = next(
        (
            question
            for question in portal.form_questions(offering)
            if question.pk == question_id and question.question_type == QuestionType.TEXT
        ),
        None,
    )
    if question is None:
        raise Http404
    text = request.POST.get(f"q{question.pk}", "")[:TEXT_MAX_LENGTH]
    result = text_filter.preview_clean(text) if text.strip() else None
    return render(request, "student/_precheck.html", {"result": result})


@require_GET
@role_required(STUDENT)
def done(request, window_id, offering_id):
    profile, offering, window = _target(request, window_id, offering_id)
    if not SubmissionReceipt.objects.filter(
        student_profile=profile, offering=offering, window=window
    ).exists():
        return redirect("feedback:form", window_id=window.pk, offering_id=offering.pk)
    waiting = portal.build_dashboard(profile, timezone.now()).waiting
    context = {"offering": offering, "window": window, "waiting": waiting}
    return render(request, "student/done.html", context)
