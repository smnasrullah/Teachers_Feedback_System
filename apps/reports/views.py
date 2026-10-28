"""The teacher's pages: dashboard, course overview, course report, comment lists, print view, note.

Every course page loads the offering first and checks ``access_for`` before anything else, so
another teacher's course answers 403 whatever the round. Results themselves are held back by
``apps.analytics`` (unreleased rounds, groups below the threshold).
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET, require_POST

from apps.academics.models import CourseOffering
from apps.core.permissions import HOD, Role, has_role, role_required
from apps.core.services.navigation import user_nav_items
from apps.feedback.models import FeedbackWindow, Question, QuestionType
from apps.feedback.services import review
from apps.reports.forms import ActionNoteForm
from apps.reports.services import teacher
from apps.reports.services.access import access_for
from apps.reports.services.comments import CommentQuery, comment_panel

READERS = (Role.TEACHER, Role.ADMIN)


def _course_url(offering, window) -> str:
    return reverse("reports:course", args=[offering.pk, window.pk])


def load_course(request, offering_id, window_id):
    """The offering and round, after the access check; access must not depend on the round."""
    offering = get_object_or_404(
        CourseOffering.objects.select_related("course__department", "semester", "teacher"),
        pk=offering_id,
    )
    access = access_for(request.user, offering)
    window = get_object_or_404(
        FeedbackWindow.objects.select_related("semester").prefetch_related(
            "departments", "level_terms"
        ),
        pk=window_id,
    )
    if not window.covers(offering):
        raise Http404
    return offering, window, access


def _focus(request):
    """The question whose comments the request searches or pages, with its query."""
    try:
        question_id = int(request.GET.get("question", ""))
    except ValueError:
        return None
    return question_id, CommentQuery.parse(request.GET)


@require_GET
@role_required(Role.TEACHER)
def dashboard(request):
    """The teacher's courses of the running semester with the status of each round."""
    profile = request.user.teacher_profile
    if profile is None:
        raise PermissionDenied
    now = timezone.now()
    context = {
        "nav_items": user_nav_items(request.user, "dashboard"),
        "courses": teacher.dashboard(profile, request.user, now),
    }
    return render(request, "reports/dashboard.html", context)


@require_GET
@role_required(Role.TEACHER)
def overview(request):
    profile = request.user.teacher_profile
    if profile is None:
        raise PermissionDenied
    now = timezone.now()
    rounds = teacher.rounds_for(profile, now)
    try:
        requested = int(request.GET.get("round", ""))
    except ValueError:
        requested = None
    window = teacher.pick_round(rounds, requested, now)
    context = {
        "nav_items": user_nav_items(request.user, "courses"),
        "rounds": rounds,
        "window": window,
        "summaries": teacher.overview(profile, window, request.user, now) if window else [],
    }
    return render(request, "reports/overview.html", context)


@require_GET
@role_required(*READERS)
def course(request, offering_id, window_id):
    offering, window, access = load_course(request, offering_id, window_id)
    report = teacher.build_report(offering, window, request.user, focus=_focus(request))
    crumbs = [{"label": offering.course.code}]
    if access.can_write_note:
        crumbs.insert(0, {"label": _("My courses"), "url": reverse("reports:overview")})
    elif has_role(request.user, HOD):
        crumbs.insert(0, {"label": _("Department"), "url": reverse("accounts:dashboard_hod")})
    context = {
        "nav_items": user_nav_items(request.user, "courses"),
        "crumbs": crumbs,
        "report": report,
        "can_write_note": access.can_write_note and report.summary.released,
        "note_form": ActionNoteForm(initial={"text": report.note.text if report.note else ""}),
    }
    return render(request, "reports/course.html", context)


@require_GET
@role_required(*READERS)
def comments(request, offering_id, window_id, question_id):
    """One question's comment list: a fragment for HTMX, the whole page otherwise."""
    offering, window, access = load_course(request, offering_id, window_id)
    question = get_object_or_404(Question, pk=question_id, question_type=QuestionType.TEXT)
    if not request.headers.get("HX-Request"):
        query = request.GET.copy()
        query["question"] = question.pk
        return redirect(f"{_course_url(offering, window)}?{query.urlencode()}#q{question.pk}")
    panel = comment_panel(
        window, offering, question, CommentQuery.parse(request.GET), viewer=request.user
    )
    return render(
        request,
        "reports/_comments.html",
        {
            "panel": panel,
            "offering": offering,
            "window": window,
            "can_write_note": access.can_write_note,
        },
    )


@require_GET
@role_required(*READERS)
def print_view(request, offering_id, window_id):
    offering, window, _access = load_course(request, offering_id, window_id)
    report = teacher.build_report(offering, window, request.user, everything=True)
    return render(request, "reports/print.html", {"report": report})


@require_POST
@role_required(Role.TEACHER)
def save_note(request, offering_id, window_id):
    offering, window, access = load_course(request, offering_id, window_id)
    if not access.can_write_note:
        raise PermissionDenied
    if not window.has_closed(timezone.now()):
        raise Http404
    form = ActionNoteForm(request.POST)
    if form.is_valid():
        teacher.save_note(offering, window, form.cleaned_data["text"])
        messages.success(request, _("Your note was saved."))
    else:
        messages.error(request, _("The note could not be saved. It may be too long."))
    return redirect(f"{_course_url(offering, window)}#action-taken")


@require_POST
@role_required(Role.TEACHER)
def report_comment(request, offering_id, window_id):
    """Send one comment of the teacher's own course to the Admin's moderation queue."""
    offering, window, access = load_course(request, offering_id, window_id)
    if not access.can_write_note:
        raise PermissionDenied
    reported = review.report(
        request.POST.get("comment", ""), offering, window, actor=request.user, request=request
    )
    if reported:
        messages.success(request, _("The comment was sent to the administrator for review."))
    else:
        messages.info(request, _("This comment has already been reported or reviewed."))
    return redirect(_course_url(offering, window))
