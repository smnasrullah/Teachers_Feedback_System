"""Admin screens for the ID registry: list, create, edit, bulk actions, HOD assignment."""

import csv

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.forms import (
    ENTRY_FORMS,
    BulkActionForm,
    HodForm,
    RegistryFilterForm,
)
from apps.accounts.models import IdRegistry, IdType
from apps.accounts.services import registry as registry_service
from apps.accounts.services import roles
from apps.core.csv_safe import safe_cell
from apps.core.permissions import Role, role_required
from apps.core.services.navigation import admin_nav_items

PAGE_SIZE = 50
FILTER_KEYS = ("q", "id_type", "status", "department")


def _list_url(query: str = "") -> str:
    """The registry list with a (re-encoded) query string, so filters survive an action."""
    encoded = QueryDict(query).urlencode()
    return reverse("accounts:registry_list") + (f"?{encoded}" if encoded else "")


def _flash_errors(request, error: ValidationError) -> None:
    for message in error.messages:
        messages.error(request, message)


@require_GET
@role_required(Role.ADMIN)
def registry_list(request):
    filter_form = RegistryFilterForm(request.GET)
    entries = filter_form.entries() if filter_form.is_valid() else IdRegistry.objects.none()
    page_obj = Paginator(entries, PAGE_SIZE).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(
        request,
        "admin_panel/registry_list.html",
        {
            "nav_items": admin_nav_items("registry"),
            "filter_form": filter_form,
            "bulk_form": BulkActionForm(),
            "page_obj": page_obj,
            "query": f"{params.urlencode()}&" if params else "",
            "return_query": request.GET.urlencode(),
            "filter_values": [(key, request.GET[key]) for key in FILTER_KEYS if key in request.GET],
        },
    )


def _entry_page(request, id_type: str, registry: IdRegistry | None = None):
    form_class = ENTRY_FORMS[id_type]
    if request.method == "POST":
        form = form_class(request.POST, request.FILES, registry=registry)
        if form.is_valid():
            try:
                form.save(actor=request.user, request=request)
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, _("The registry entry was saved."))
                return redirect("accounts:registry_list")
    else:
        form = form_class(registry=registry)
    return render(
        request,
        "admin_panel/registry_form.html",
        {
            "nav_items": admin_nav_items("registry"),
            "form": form,
            "registry": registry,
            "id_type": id_type,
            "hod_form": HodForm(initial={"department": registry.department_id})
            if registry is not None and id_type == IdType.TEACHER
            else None,
        },
    )


@require_http_methods(["GET", "POST"])
@role_required(Role.ADMIN)
def registry_create(request, id_type):
    if id_type not in ENTRY_FORMS:
        raise Http404
    return _entry_page(request, id_type)


@require_http_methods(["GET", "POST"])
@role_required(Role.ADMIN)
def registry_edit(request, pk):
    registry = get_object_or_404(
        IdRegistry.objects.select_related("department", "claimed_by"), pk=pk
    )
    return _entry_page(request, registry.id_type, registry)


def codes_csv_response(issued) -> HttpResponse:
    """The only place plaintext codes exist: this response. Nothing is kept afterwards."""
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="activation-codes-{stamp}.csv"'
    response.write("﻿")
    writer = csv.writer(response)
    writer.writerow([_("ID"), _("Type"), _("Department"), _("Activation code"), _("Valid until")])
    for item in issued:
        entry = item.registry
        valid_until = timezone.localtime(entry.activation_expires_at).strftime("%Y-%m-%d %H:%M")
        writer.writerow(
            [
                safe_cell(entry.external_id),
                entry.get_id_type_display(),
                safe_cell(entry.department.code),
                item.code,
                valid_until,
            ]
        )
    return response


@require_POST
@never_cache
@role_required(Role.ADMIN)
def registry_bulk(request):
    form = BulkActionForm(request.POST)
    back = _list_url(request.POST.get("return_query", ""))
    if not form.is_valid():
        for errors in form.errors.values():
            for message in errors:
                messages.error(request, message)
        return redirect(back)
    entries, action = form.entries(), form.cleaned_data["action"]
    try:
        if action == BulkActionForm.ACTION_CODES:
            issued = registry_service.issue_activation_codes(
                entries,
                valid_days=form.cleaned_data["valid_days"],
                actor=request.user,
                request=request,
            )
            if issued:
                return codes_csv_response(issued)
            messages.warning(request, _("Only unclaimed entries can receive an activation code."))
        elif action == BulkActionForm.ACTION_REVOKE:
            count = registry_service.revoke(entries, actor=request.user, request=request)
            messages.success(
                request,
                ngettext("%(count)d entry was revoked.", "%(count)d entries were revoked.", count)
                % {"count": count},
            )
        else:
            count = registry_service.activate(entries, actor=request.user, request=request)
            messages.success(
                request,
                ngettext(
                    "%(count)d entry was re-activated.",
                    "%(count)d entries were re-activated.",
                    count,
                )
                % {"count": count},
            )
    except ValidationError as error:
        _flash_errors(request, error)
    return redirect(back)


@require_POST
@role_required(Role.ADMIN)
def registry_hod(request, pk):
    registry = get_object_or_404(
        IdRegistry.objects.select_related("teacher_profile"), pk=pk, id_type=IdType.TEACHER
    )
    profile = registry.teacher_profile
    try:
        if request.POST.get("action") == "remove":
            if roles.remove_hod(profile, actor=request.user, request=request):
                messages.success(request, _("The head of department was removed."))
        else:
            form = HodForm(request.POST)
            if not form.is_valid():
                for errors in form.errors.values():
                    for message in errors:
                        messages.error(request, message)
                return redirect("accounts:registry_edit", pk=pk)
            replaced = roles.assign_hod(
                profile, form.cleaned_data["department"], actor=request.user, request=request
            )
            messages.success(
                request,
                _("The head of department was assigned and the previous head was replaced.")
                if replaced
                else _("The head of department was assigned."),
            )
    except ValidationError as error:
        _flash_errors(request, error)
    return redirect("accounts:registry_edit", pk=pk)
