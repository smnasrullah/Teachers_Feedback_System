"""Admin CRUD screens for the academic structure; one set of views serves every model."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods

from apps.academics.screens import SCREENS, Screen
from apps.academics.services import catalog
from apps.core.permissions import Role, role_required
from apps.core.services.navigation import admin_nav_items

PAGE_SIZE = 50


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
            catalog.save(screen, form, actor=request.user, request=request)
            messages.success(request, _("The %(what)s was saved.") % {"what": screen.singular})
            return redirect("academics:list", entity=screen.key)
    else:
        form = screen.form_class(instance=obj)
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
