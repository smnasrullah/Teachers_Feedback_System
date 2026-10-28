"""Admin CRUD screens for the academic structure; one set of views serves every model."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.http import require_GET, require_http_methods

from apps.academics.forms import AssignFilterForm
from apps.academics.models import CourseOffering, Semester
from apps.academics.screens import SCREENS, Screen
from apps.academics.services import assignments, catalog, semesters
from apps.accounts.models import TeacherProfile
from apps.core.permissions import Role, role_required
from apps.core.services.navigation import admin_nav_items

PAGE_SIZE = 50
ASSIGN_PAGE_SIZE = 25
TEACHER_FIELD = "teacher_"


def _screen(entity: str) -> Screen:
    try:
        return SCREENS[entity]
    except KeyError:
        raise Http404 from None


@require_GET
@role_required(Role.ADMIN)
def entity_list(request, entity):
    screen = _screen(entity)
    form = screen.filter_form_class()(request.GET)
    records = screen.queryset()
    records = (
        screen.apply_filters(records, form.cleaned_data) if form.is_valid() else records.none()
    )
    page_obj = Paginator(records, PAGE_SIZE).get_page(request.GET.get("page"))
    rows = [
        {"obj": obj, "cells": [(column, column.value(obj)) for column in screen.columns]}
        for obj in page_obj
    ]
    params = request.GET.copy()
    params.pop("page", None)
    return render(
        request,
        "admin_panel/academics_list.html",
        {
            "nav_items": admin_nav_items(f"academics-{screen.key}"),
            "screen": screen,
            "filter_form": form,
            "page_obj": page_obj,
            "rows": rows,
            "query": f"{params.urlencode()}&" if params else "",
        },
    )


def _form_page(request, screen: Screen, obj=None):
    if request.method == "POST":
        form = screen.form_class(request.POST, instance=obj)
        if form.is_valid():
            try:
                catalog.save(screen, form, actor=request.user, request=request)
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, _("The %(what)s was saved.") % {"what": screen.singular})
                return redirect("academics:list", entity=screen.key)
    else:
        suggested = obj is None and screen.suggest and request.GET.get("suggested")
        form = screen.form_class(instance=obj, initial=screen.suggest() if suggested else None)
    return render(
        request,
        "admin_panel/academics_form.html",
        {
            "nav_items": admin_nav_items(f"academics-{screen.key}"),
            "screen": screen,
            "form": form,
            "obj": obj,
        },
    )


@require_http_methods(["GET", "POST"])
@role_required(Role.ADMIN)
def entity_create(request, entity):
    return _form_page(request, _screen(entity))


@require_http_methods(["GET", "POST"])
@role_required(Role.ADMIN)
def entity_edit(request, entity, pk):
    screen = _screen(entity)
    return _form_page(request, screen, get_object_or_404(screen.queryset(), pk=pk))


@require_http_methods(["GET", "POST"])
@role_required(Role.ADMIN)
def entity_delete(request, entity, pk):
    screen = _screen(entity)
    obj = get_object_or_404(screen.queryset(), pk=pk)
    if request.method == "POST":
        try:
            catalog.delete(screen, obj, actor=request.user, request=request)
        except ValidationError as error:
            messages.error(request, error.messages[0])
            return redirect("academics:edit", entity=screen.key, pk=pk)
        messages.success(request, _("The %(what)s was deleted.") % {"what": screen.singular})
        return redirect("academics:list", entity=screen.key)
    return render(
        request,
        "admin_panel/academics_delete.html",
        {"nav_items": admin_nav_items(f"academics-{screen.key}"), "screen": screen, "obj": obj},
    )


def _assign_url(query: str = "") -> str:
    encoded = QueryDict(query).urlencode()
    return reverse("academics:assign_teachers") + (f"?{encoded}" if encoded else "")


def _teacher_choices() -> list[tuple[int, str]]:
    teachers = TeacherProfile.objects.select_related("registry")
    return sorted(
        (
            (teacher.pk, f"{teacher.registry.external_id} · {teacher.registry.full_name or '—'}")
            for teacher in teachers
        ),
        key=lambda choice: choice[1],
    )


def _assign_post(request):
    changes = {
        int(name.removeprefix(TEACHER_FIELD)): int(value)
        for name, value in request.POST.items()
        if name.startswith(TEACHER_FIELD)
        and name.removeprefix(TEACHER_FIELD).isdigit()
        and value.isdigit()
    }
    try:
        count = assignments.assign_teachers(changes, actor=request.user, request=request)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(
            request,
            ngettext(
                "%(count)d assignment was changed.",
                "%(count)d assignments were changed.",
                count,
            )
            % {"count": count},
        )
    return redirect(_assign_url(request.POST.get("return_query", "")))


@require_http_methods(["GET", "POST"])
@role_required(Role.ADMIN)
def assign_teachers(request):
    if request.method == "POST":
        return _assign_post(request)
    form = AssignFilterForm(request.GET)
    valid = form.is_valid()
    semester = (valid and form.cleaned_data["semester"]) or (
        semesters.current_semester() or Semester.objects.first()
    )
    offerings = CourseOffering.objects.select_related("course__department").filter(
        semester=semester
    )
    if valid and form.cleaned_data["department"]:
        offerings = offerings.filter(course__department=form.cleaned_data["department"])
    page_obj = Paginator(offerings if valid else offerings.none(), ASSIGN_PAGE_SIZE).get_page(
        request.GET.get("page")
    )
    params = request.GET.copy()
    params.pop("page", None)
    return render(
        request,
        "admin_panel/assign_teachers.html",
        {
            "nav_items": admin_nav_items("assign"),
            "filter_form": form,
            "semester": semester,
            "page_obj": page_obj,
            "teachers": _teacher_choices(),
            "return_query": request.GET.urlencode(),
            "query": f"{params.urlencode()}&" if params else "",
        },
    )
