"""Admin screens for enrollment: by level/term, single enrol and remove, who is missing."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from apps.accounts.models import registry_index
from apps.accounts.services.student_id_policy import (
    visible_full_name,
    visible_student_id,
    with_visible_ids,
)
from apps.core.permissions import Role, role_required
from apps.core.services.navigation import admin_nav_items
from apps.enrollment import selectors
from apps.enrollment.forms import EnrollForm, EnrollmentFilterForm, GroupForm, MissingFilterForm
from apps.enrollment.models import Enrollment
from apps.enrollment.services import enrollments

PAGE_SIZE = 50


def _page(request, template: str, nav: str, **context):
    return render(request, template, {"nav_items": admin_nav_items(nav), **context})


def _query(request) -> str:
    params = request.GET.copy()
    params.pop("page", None)
    return f"{params.urlencode()}&" if params else ""


@require_http_methods(["GET", "POST"])
@never_cache
@role_required(Role.ADMIN)
def group_enroll(request):
    posted = request.method == "POST"
    form = GroupForm(request.POST if posted else request.GET or None)
    plan = None
    if form.is_valid():
        program, level_term = form.cleaned_data["program"], form.cleaned_data["level_term"]
        try:
            if posted:
                plan = enrollments.enroll_group(
                    program, level_term, actor=request.user, request=request
                )
                messages.success(
                    request,
                    ngettext(
                        "%(count)d enrollment was created.",
                        "%(count)d enrollments were created.",
                        len(plan.new),
                    )
                    % {"count": len(plan.new)},
                )
                return redirect("enrollment:group")
            plan = enrollments.plan_group(program, level_term)
        except ValidationError as error:
            messages.error(request, error.messages[0])
    return _page(request, "admin_panel/enroll_group.html", "enroll-group", form=form, plan=plan)


@require_http_methods(["GET", "POST"])
@role_required(Role.ADMIN)
def enrollment_list(request):
    form = EnrollForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            enrollments.enroll(
                form.cleaned_data["student_id"],
                form.cleaned_data["offering"],
                status=form.cleaned_data["status"],
                actor=request.user,
                request=request,
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, _("The student was enrolled."))
            return redirect("enrollment:list")
    filters = EnrollmentFilterForm(request.GET)
    records = Enrollment.objects.select_related(
        "offering__course", "offering__semester", "student_profile__registry"
    ).order_by("offering__course__code", "pk")
    if filters.is_valid():
        data = filters.cleaned_data
        if data["offering"]:
            records = records.filter(offering=data["offering"])
        else:
            records = records.filter(offering__semester__is_current=True)
        if data["student_id"]:
            index = registry_index(data["student_id"])
            records = records.filter(student_profile__registry__external_id_index=index)
        if data["status"]:
            records = records.filter(status=data["status"])
    else:
        records = records.none()
    page_obj = Paginator(records, PAGE_SIZE).get_page(request.GET.get("page"))
    rows = [
        {
            "enrollment": enrollment,
            "student_id": visible_student_id(request.user, enrollment.student_profile),
            "full_name": visible_full_name(request.user, enrollment.student_profile),
        }
        for enrollment in page_obj
    ]
    return _page(
        request,
        "admin_panel/enrollment_list.html",
        "enrollments",
        form=form,
        filter_form=filters,
        page_obj=page_obj,
        rows=rows,
        query=_query(request),
    )


@require_http_methods(["GET", "POST"])
@role_required(Role.ADMIN)
def enrollment_remove(request, pk):
    enrollment = get_object_or_404(
        Enrollment.objects.select_related("offering__course", "student_profile__registry"), pk=pk
    )
    if request.method == "POST":
        try:
            enrollments.remove(enrollment, actor=request.user, request=request)
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, _("The enrollment was removed."))
        return redirect("enrollment:list")
    return _page(
        request,
        "admin_panel/enrollment_remove.html",
        "enrollments",
        enrollment=enrollment,
        student_id=visible_student_id(request.user, enrollment.student_profile),
    )


@require_GET
@role_required(Role.ADMIN)
def missing_enrollment(request):
    form = MissingFilterForm(request.GET)
    students = selectors.students_missing_enrollment()
    if form.is_valid():
        data = form.cleaned_data
        if data["department"]:
            students = students.filter(program__department=data["department"])
        if data["level_term"]:
            students = students.filter(level_term=data["level_term"])
    else:
        students = students.none()
    students = with_visible_ids(
        students.select_related("program__department", "level_term"), request.user
    ).order_by("program__department__code", "level_term__order", "pk")
    page_obj = Paginator(students, PAGE_SIZE).get_page(request.GET.get("page"))
    return _page(
        request,
        "admin_panel/enrollment_missing.html",
        "enroll-missing",
        filter_form=form,
        page_obj=page_obj,
        query=_query(request),
    )
