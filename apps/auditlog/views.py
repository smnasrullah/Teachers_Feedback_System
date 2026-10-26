"""The Admin's audit log: filter, export, verify the hash chain."""

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import StreamingHttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST
from django_ratelimit.decorators import ratelimit

from apps.auditlog.forms import AuditFilterForm
from apps.auditlog.services import audit, search
from apps.core.permissions import Role, role_required
from apps.core.services.navigation import admin_nav_items

PAGE_SIZE = 50
VERIFY_RATE = "6/m"


def _criteria(request) -> tuple[AuditFilterForm, dict]:
    form = AuditFilterForm(request.GET or None)
    if form.is_valid():
        return form, {key: value for key, value in form.cleaned_data.items() if value}
    return form, {}


@require_GET
@role_required(Role.ADMIN)
def log(request):
    form, criteria = _criteria(request)
    page = Paginator(search.filtered(criteria), PAGE_SIZE).get_page(request.GET.get("page"))
    params = {key: str(value) for key, value in criteria.items()}
    context = {
        "nav_items": admin_nav_items("audit"),
        "form": form,
        "page_obj": page,
        "actions": search.known_actions(),
        "object_types": search.known_object_types(),
        "export_query": urlencode(params),
        "page_query": f"{urlencode(params)}&" if params else "",
    }
    return render(request, "admin_panel/audit_log.html", context)


@require_GET
@role_required(Role.ADMIN)
def export(request):
    _form, criteria = _criteria(request)
    audit.record(
        "audit.exported",
        request=request,
        metadata={"filters": sorted(criteria)},
    )
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M")
    response = StreamingHttpResponse(
        search.export_lines(search.filtered(criteria)), content_type="text/csv; charset=utf-8"
    )
    response["Content-Disposition"] = f'attachment; filename="audit-log-{stamp}.csv"'
    return response


@require_POST
@role_required(Role.ADMIN)
@ratelimit(key="user", rate=VERIFY_RATE, method="POST", block=False)
def verify(request):
    if request.limited:
        messages.error(request, _("Too many checks at once. Wait a moment."))
        return redirect(reverse("auditlog:log"))
    report = audit.verify_chain()
    audit.record(
        "audit.chain_verified",
        request=request,
        metadata={"checked": report.checked, "ok": report.ok, "broken_at": report.broken_at},
    )
    if report.ok:
        messages.success(
            request,
            _("The audit trail is intact: %(count)s events checked.") % {"count": report.checked},
        )
    else:
        messages.error(
            request,
            _("The audit trail was changed: event %(id)s no longer matches its record.")
            % {"id": report.broken_at},
        )
    return redirect(reverse("auditlog:log"))
