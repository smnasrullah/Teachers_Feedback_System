"""Downloads of the reports as CSV, Excel and PDF (BLUEPRINT §5.4).

Each view reuses the access rule of the page it exports: the course report goes through
``load_course`` (its teacher, the head of its department, an Admin), the department report and
the pending list belong to the signed-in head of department (an Admin names the department),
and the university report is the Admin's. What a file contains is decided by the report
services, so the response threshold and the release rule hold here as on screen. Every
download is recorded in the audit trail.
"""

from django.core.exceptions import BadRequest
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET
from django_ratelimit.decorators import ratelimit

from apps.academics.models import Department, LevelTerm
from apps.core.permissions import HOD, Role, has_role, role_required
from apps.reports.forms import UniversityFilterForm
from apps.reports.services import department as department_service
from apps.reports.services import exports, teacher, university
from apps.reports.services.exports import builders
from apps.reports.services.exports.model import Format
from apps.reports.services.exports.pdf import PdfUnavailable
from apps.reports.views import READERS, load_course

EXPORT_RATE = "30/m"
GUARDS = (ratelimit(key="user", rate=EXPORT_RATE, method="GET", block=True), require_GET)


def _guarded(view):
    for guard in GUARDS:
        view = guard(view)
    return view


def _int(raw) -> int | None:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _download(export, fmt, request, **audit_fields) -> HttpResponse:
    try:
        file = exports.deliver(export, Format(fmt), request=request, **audit_fields)
    except PdfUnavailable:
        return HttpResponse(
            _("PDF files cannot be made on this server right now."),
            status=503,
            content_type="text/plain; charset=utf-8",
        )
    response = HttpResponse(file.content, content_type=file.content_type)
    response["Content-Disposition"] = f'attachment; filename="{file.filename}"'
    response["Cache-Control"] = "private, no-store"
    return response


def _department_of(request) -> Department:
    """The head's own department; an Admin names one with ``?department=``."""
    if has_role(request.user, Role.ADMIN):
        department = Department.objects.filter(pk=_int(request.GET.get("department"))).first()
        if department is None:
            raise BadRequest("An Admin must name a department.")
        return department
    return request.user.hod_department


@_guarded
@role_required(*READERS)
def course(request, offering_id, window_id, fmt):
    offering, window, _access = load_course(request, offering_id, window_id)
    export = builders.teacher_course(offering, window, request.user, timezone.now())
    return _download(
        export,
        fmt,
        request,
        target=offering,
        department_id=offering.course.department_id,
    )


@_guarded
@role_required(HOD, Role.ADMIN)
def department(request, fmt):
    department = _department_of(request)
    now = timezone.now()
    window = teacher.pick_round(
        department_service.rounds(department, now), _int(request.GET.get("round")), now
    )
    if window is None:
        raise Http404
    threshold = department_service.threshold_from(request.GET.get("below"))
    export = builders.department_report(department, window, request.user, now, threshold)
    return _download(export, fmt, request, target=department, department_id=department.pk)


@_guarded
@role_required(HOD, Role.ADMIN)
def pending(request, fmt):
    department = _department_of(request)
    now = timezone.now()
    window = department_service.pick_pending_round(
        department_service.rounds(department, now), _int(request.GET.get("round")), now
    )
    if window is None:
        raise Http404
    offerings = department_service.offerings_in_scope(department, window)
    chosen = _int(request.GET.get("course"))
    if chosen is not None:
        offerings = [department_service.offering_in_scope(department, window, chosen)]
    level = _int(request.GET.get("level"))
    level_term = LevelTerm.objects.filter(pk=level).first() if level is not None else None
    export = builders.pending_submissions(department, window, request.user, offerings, level_term)
    return _download(export, fmt, request, target=department, department_id=department.pk)


@_guarded
@role_required(Role.ADMIN)
def university_report(request, fmt):
    form = UniversityFilterForm(request.GET)
    if not form.is_valid():
        raise BadRequest("Invalid filter.")
    criteria = form.cleaned_data
    now = timezone.now()
    available = university.rounds(criteria["semester"], now)
    window = university.pick_round(available, criteria["round"], now)
    if window is None:
        raise Http404
    filters = university.Filters(
        criteria["semester"], criteria["department"], criteria["level_term"], window
    )
    export = builders.university_report(filters, request.user, now)
    return _download(export, fmt, request, department_id=None)
