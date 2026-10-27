"""Admin screens for feedback rounds: list, create/edit, and a preview of what students get."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from apps.academics.models import CourseOffering, CourseType
from apps.core.permissions import Role, role_required
from apps.core.services.navigation import admin_nav_items
from apps.feedback.forms import WindowForm
from apps.feedback.models import FeedbackWindow, Question
from apps.feedback.services import windows

PAGE_SIZE = 25


def _page(request, template: str, **context):
    return render(request, template, {"nav_items": admin_nav_items("windows"), **context})


@require_GET
@never_cache
@role_required(Role.ADMIN)
def window_list(request):
    now = timezone.now()
    records = FeedbackWindow.objects.select_related("semester").prefetch_related(
        "departments", "level_terms"
    )
    page_obj = Paginator(records, PAGE_SIZE).get_page(request.GET.get("page"))
    rows = [{"window": window, "status": window.status(now)} for window in page_obj]
    return _page(request, "admin_panel/window_list.html", page_obj=page_obj, rows=rows, query="")


def _form_page(request, window=None):
    if request.method == "POST":
        form = WindowForm(request.POST, instance=window)
        if form.is_valid():
            try:
                windows.save_window(form, actor=request.user, request=request)
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, _("The feedback round was saved."))
                return redirect("feedback:windows")
    else:
        form = WindowForm(instance=window)
    return _page(request, "admin_panel/window_form.html", form=form, window=window)


@require_http_methods(["GET", "POST"])
@role_required(Role.ADMIN)
def window_create(request):
    return _form_page(request)


@require_http_methods(["GET", "POST"])
@role_required(Role.ADMIN)
def window_edit(request, pk):
    return _form_page(request, get_object_or_404(FeedbackWindow, pk=pk))


@require_GET
@never_cache
@role_required(Role.ADMIN)
def window_preview(request, pk):
    window = get_object_or_404(
        FeedbackWindow.objects.select_related("semester").prefetch_related(
            "departments", "level_terms"
        ),
        pk=pk,
    )
    offerings = [
        offering
        for offering in CourseOffering.objects.filter(semester=window.semester).select_related(
            "course"
        )
        if window.covers(offering)
    ]
    forms = [
        (label, Question.objects.for_course_type(course_type).select_related("category"))
        for course_type, label in CourseType.choices
    ]
    return _page(
        request,
        "admin_panel/window_preview.html",
        window=window,
        status=window.status(timezone.now()),
        offering_count=len(offerings),
        forms=forms,
    )
