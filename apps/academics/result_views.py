"""Admin screens for results: offerings of a semester with their grading progress, and the
grade sheet of one offering (entry and publishing)."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from apps.academics.forms import GradeSheetForm, ResultFilterForm
from apps.academics.models import CourseOffering
from apps.academics.services import results
from apps.accounts.services.student_id_policy import visible_full_name, visible_student_id
from apps.core.permissions import Role, role_required
from apps.core.services.navigation import admin_nav_items

PAGE_SIZE = 50


@require_GET
@role_required(Role.ADMIN)
def result_index(request):
    form = ResultFilterForm(request.GET)
    semester = form.semester_or_current()
    offerings = (
        CourseOffering.objects.filter(semester=semester)
        .select_related("course__department")
        .annotate(
            enrolled=Count("enrollments"),
            graded=Count("enrollments__result"),
            published=Count("enrollments__result", filter=Q(enrollments__result__published=True)),
        )
        .order_by("course__code", "section", "pk")
    )
    if form.is_valid() and form.cleaned_data["department"]:
        offerings = offerings.filter(course__department=form.cleaned_data["department"])
    page_obj = Paginator(offerings if form.is_valid() else offerings.none(), PAGE_SIZE).get_page(
        request.GET.get("page")
    )
    params = request.GET.copy()
    params.pop("page", None)
    return render(
        request,
        "admin_panel/result_index.html",
        {
            "nav_items": admin_nav_items("results"),
            "filter_form": form,
            "semester": semester,
            "page_obj": page_obj,
            "query": f"{params.urlencode()}&" if params else "",
        },
    )


@require_http_methods(["GET", "POST"])
@never_cache
@role_required(Role.ADMIN)
def grade_sheet(request, pk):
    offering = get_object_or_404(
        CourseOffering.objects.select_related("course__department", "semester"), pk=pk
    )
    enrollments = list(results.grade_sheet(offering))
    posted = request.method == "POST"
    form = GradeSheetForm(request.POST if posted else None, enrollments=enrollments)
    if posted and form.is_valid():
        try:
            summary = results.save_grades(
                offering,
                form.grades(),
                publish="publish" in request.POST,
                actor=request.user,
                request=request,
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(
                request,
                _("Saved: %(created)d new, %(changed)d changed, %(published)d published.")
                % {
                    "created": summary.created,
                    "changed": summary.changed,
                    "published": summary.published,
                },
            )
            return redirect("academics:grade_sheet", pk=offering.pk)
    rows = [
        {
            "enrollment": enrollment,
            "result": getattr(enrollment, "result", None),
            "student_id": visible_student_id(request.user, enrollment.student_profile),
            "full_name": visible_full_name(request.user, enrollment.student_profile),
            "field": form[f"{GradeSheetForm.PREFIX}{enrollment.pk}"],
        }
        for enrollment in enrollments
    ]
    return render(
        request,
        "admin_panel/grade_sheet.html",
        {"nav_items": admin_nav_items("results"), "offering": offering, "form": form, "rows": rows},
    )
