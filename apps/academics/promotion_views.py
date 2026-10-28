"""Admin screens for promotion: the rule, the preview table with per-student overrides, and the
confirmation that applies exactly the preview the admin reviewed."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from apps.academics.forms import OverrideForm, PromotionFilterForm, PromotionRuleForm
from apps.academics.models import Outcome, PromotionOverride, PromotionRule, Semester
from apps.academics.selectors import promotion_rows
from apps.academics.services import promotion, semesters
from apps.accounts.models import StudentProfile
from apps.accounts.services.student_id_policy import visible_full_name, visible_student_id
from apps.core.permissions import Role, role_required
from apps.core.services.navigation import admin_nav_items

PAGE_SIZE = 50


def _page(request, template: str, nav: str, **context):
    return render(request, template, {"nav_items": admin_nav_items(nav), **context})


def _preview_url(semester) -> str:
    return f"{reverse('academics:promotion')}?semester={semester.pk}"


def _summary(planned, semester) -> dict:
    counts = planned.counts()
    return {
        "ended": promotion.has_ended(semester),
        "ends_on": semesters.short_date(semester.end_date),
        "counts": [(label, counts.get(value, 0)) for value, label in Outcome.choices],
        "overridden": sum(decision.overridden for decision in planned.decisions),
        "enrollments": sum(len(decision.enrollments) for decision in planned.decisions),
        "unplaced": sum(len(decision.unplaced_course_ids) for decision in planned.decisions),
        "target": (
            Semester.objects.get(pk=planned.target_semester_id)
            if planned.target_semester_id
            else None
        ),
    }


@require_http_methods(["GET", "POST"])
@role_required(Role.ADMIN)
def promotion_rule(request):
    form = PromotionRuleForm(
        request.POST if request.method == "POST" else None, instance=PromotionRule.current()
    )
    if request.method == "POST" and form.is_valid():
        promotion.save_rule(form, actor=request.user, request=request)
        messages.success(request, _("The promotion rule was saved."))
        return redirect("academics:promotion_rule")
    return _page(request, "admin_panel/promotion_rule.html", "promotion-rule", form=form)


@require_GET
@never_cache
@role_required(Role.ADMIN)
def promotion_preview(request):
    form = PromotionFilterForm(request.GET)
    semester = form.semester_or_current()
    planned = promotion.preview(semester) if semester else None
    decisions = planned.decisions if planned and form.is_valid() else ()
    if decisions and form.cleaned_data["outcome"]:
        decisions = [d for d in decisions if d.outcome == form.cleaned_data["outcome"]]
    page_obj = Paginator(decisions, PAGE_SIZE).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return _page(
        request,
        "admin_panel/promotion_preview.html",
        "promotion",
        filter_form=form,
        semester=semester,
        planned=planned,
        summary=_summary(planned, semester) if planned else None,
        page_obj=page_obj,
        rows=promotion_rows(page_obj.object_list, request.user),
        query=f"{params.urlencode()}&" if params else "",
    )


@require_http_methods(["GET", "POST"])
@never_cache
@role_required(Role.ADMIN)
def promotion_confirm(request, semester_pk):
    semester = get_object_or_404(Semester, pk=semester_pk)
    planned = promotion.preview(semester)
    source = request.POST if request.method == "POST" else request.GET
    if source.get("fingerprint", "") != planned.fingerprint():
        messages.error(request, _("The preview changed. Review it again before applying."))
        return redirect(_preview_url(semester))
    if request.method == "POST":
        try:
            count = promotion.apply(planned, actor=request.user, request=request)
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(
                request,
                ngettext(
                    "The promotion was applied to %(count)d student.",
                    "The promotion was applied to %(count)d students.",
                    count,
                )
                % {"count": count},
            )
        return redirect(_preview_url(semester))
    return _page(
        request,
        "admin_panel/promotion_confirm.html",
        "promotion",
        semester=semester,
        planned=planned,
        summary=_summary(planned, semester),
        fingerprint=planned.fingerprint(),
    )


@require_http_methods(["GET", "POST"])
@role_required(Role.ADMIN)
def promotion_override(request, semester_pk, student_pk):
    semester = get_object_or_404(Semester, pk=semester_pk)
    student = get_object_or_404(
        StudentProfile.objects.filter(enrollments__offering__semester=semester)
        .select_related("registry", "level_term")
        .distinct(),
        pk=student_pk,
    )
    override = PromotionOverride.objects.filter(student_profile=student, semester=semester).first()
    posted = request.method == "POST"
    if posted and request.POST.get("action") == "clear":
        if override is not None:
            try:
                promotion.clear_override(override, actor=request.user, request=request)
            except ValidationError as error:
                messages.error(request, error.messages[0])
            else:
                messages.success(request, _("The override was removed."))
        return redirect(_preview_url(semester))
    initial = {"outcome": override.outcome, "reason": override.reason} if override else None
    form = OverrideForm(request.POST if posted else None, initial=initial)
    if posted and form.is_valid():
        try:
            promotion.set_override(
                student,
                semester,
                form.cleaned_data["outcome"],
                form.cleaned_data["reason"],
                actor=request.user,
                request=request,
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, _("The override was saved."))
            return redirect(_preview_url(semester))
    return _page(
        request,
        "admin_panel/promotion_override.html",
        "promotion",
        semester=semester,
        student=student,
        student_id=visible_student_id(request.user, student),
        full_name=visible_full_name(request.user, student),
        override=override,
        form=form,
    )
