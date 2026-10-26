"""Admin screens for bulk CSV import: choose a kind, preview the file, confirm."""

import csv

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.academics.forms import ImportUploadForm
from apps.academics.services import importers, staging
from apps.accounts.views.registry import codes_csv_response
from apps.core.permissions import Role, role_required
from apps.core.services.navigation import admin_nav_items


def _importer_class(kind: str) -> type[importers.Importer]:
    try:
        return importers.IMPORTERS[kind]
    except KeyError:
        raise Http404 from None


def _page(request, template: str, **context):
    return render(request, template, {"nav_items": admin_nav_items("import"), **context})


@require_GET
@role_required(Role.ADMIN)
def import_index(request):
    return _page(request, "admin_panel/import_index.html", kinds=importers.IMPORTERS.values())


@require_GET
@role_required(Role.ADMIN)
def import_template(request, kind):
    importer = _importer_class(kind)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{importer.key}-template.csv"'
    response.write("﻿")
    csv.writer(response).writerows(importers.template_rows(importer))
    return response


@require_http_methods(["GET", "POST"])
@never_cache
@role_required(Role.ADMIN)
def import_upload(request, kind):
    importer_class = _importer_class(kind)
    posted = request.method == "POST"
    form = ImportUploadForm(
        request.POST if posted else None,
        request.FILES if posted else None,
        importer=importer_class,
    )
    if posted and form.is_valid():
        options = form.options()
        text = form.cleaned_data["file"]
        try:
            result = importers.run(
                importer_class(**options), text, apply=False, actor=request.user, request=request
            )
        except importers.ImportRejected as error:
            form.add_error("file", error)
        else:
            return _page(
                request,
                "admin_panel/import_preview.html",
                importer=importer_class,
                result=result,
                token=staging.stash(request.user, kind, text, options) if result.ok else "",
            )
    return _page(request, "admin_panel/import_upload.html", importer=importer_class, form=form)


@require_POST
@never_cache
@role_required(Role.ADMIN)
def import_apply(request, kind):
    importer_class = _importer_class(kind)
    stashed = staging.take(request.user, kind, request.POST.get("token", ""))
    if stashed is None:
        messages.error(request, _("The preview expired. Upload the file again."))
        return redirect("academics:import_upload", kind=kind)
    try:
        result = importers.run(
            importer_class(**stashed["options"]),
            stashed["text"],
            apply=True,
            actor=request.user,
            request=request,
        )
    except importers.ImportRejected as error:
        messages.error(request, error.messages[0])
        return redirect("academics:import_upload", kind=kind)
    if not result.ok:
        messages.error(request, _("The data changed after the preview. Upload the file again."))
        return redirect("academics:import_upload", kind=kind)
    messages.success(
        request,
        ngettext(
            "%(count)d record was imported.", "%(count)d records were imported.", result.created
        )
        % {"count": result.created},
    )
    if result.issued:
        return codes_csv_response(result.issued)
    return redirect("academics:import_index")
