"""The head of department's pages: department overview, pending submissions, audit log.

The department is always the signed-in head's own (``request.user.hod_department``); no URL
carries a department, so there is nothing to tamper with. An offering named in a query or a
form must belong to it, else 403. Drilling into a teacher's course uses the existing read-only
course report, whose access check already admits the head of the offering's department.
"""

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST
from django_ratelimit.decorators import ratelimit

from apps.academics.models import LevelTerm
from apps.core.permissions import HOD, role_required
from apps.core.services.navigation import user_nav_items
from apps.reports.services import department as service
from apps.reports.services import teacher

PAGE_SIZE = 25
REMIND_RATE = "60/m"
FILTER_KEYS = ("round", "course", "level", "page")


def _int(raw) -> int | None:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@require_GET
@role_required(HOD)
def overview(request):
    department = request.user.hod_department
    now = timezone.now()
    available = service.rounds(department, now)
    window = teacher.pick_round(available, _int(request.GET.get("round")), now)
    threshold = service.threshold_from(request.GET.get("below"))
    context = {
        "nav_items": user_nav_items(request.user, "dashboard"),
        "department": department,
        "rounds": available,
        "window": window,
        "threshold": threshold,
        "overview": service.build_overview(department, window, request.user, now, threshold)
        if window
        else None,
        "round_open": bool(window and window.is_open(now)),
        "closes_at": window.closes_at if window else None,
        "export_query": f"?{urlencode({'round': window.pk, 'below': f'{threshold:.1f}'})}"
        if window
        else "",
    }
    return render(request, "reports/hod_overview.html", context)


def _pending_context(request, department, now):
    available = service.rounds(department, now)
    window = service.pick_pending_round(available, _int(request.GET.get("round")), now)
    context = {
        "nav_items": user_nav_items(request.user, "pending"),
        "department": department,
        "rounds": available,
        "window": window,
        "level_terms": service.level_terms(),
        "round_open": bool(window and window.is_open(now)),
    }
    if window is None:
        return context
    offerings = service.offerings_in_scope(department, window)
    course = _int(request.GET.get("course"))
    chosen = None
    if course is not None:
        chosen = service.offering_in_scope(department, window, course)
    level = _int(request.GET.get("level"))
    level_term = LevelTerm.objects.filter(pk=level).first() if level is not None else None
    pending = service.pending_list(
        department, window, request.user, [chosen] if chosen else offerings, level_term
    )
    page = Paginator(pending.rows, PAGE_SIZE).get_page(request.GET.get("page"))
    filters = {"round": window.pk}
    if chosen:
        filters["course"] = chosen.pk
    if level_term:
        filters["level"] = level_term.pk
    context |= {
        "offerings": offerings,
        "chosen": chosen,
        "level_term": level_term,
        "page_obj": page,
        "total": len(pending.rows),
        "others": pending.others,
        "filter_query": urlencode(filters),
        "export_query": f"?{urlencode(filters)}",
        "page_query": f"{urlencode(filters)}&",
    }
    return context


@require_GET
@role_required(HOD)
def pending(request):
    context = _pending_context(request, request.user.hod_department, timezone.now())
    return render(request, "reports/hod_pending.html", context)


@require_POST
@role_required(HOD)
@ratelimit(key="user", rate=REMIND_RATE, method="POST", block=False)
def remind(request):
    """Queue a reminder for one listed student or for every pending student of a course. The
    answer is the same sentence either way, so it says nothing about who else is pending."""
    department = request.user.hod_department
    target = reverse("reports:hod_pending")
    keep = {key: request.GET[key] for key in FILTER_KEYS if key in request.GET}
    back = redirect(f"{target}?{urlencode(keep)}" if keep else target)
    if request.limited:
        messages.error(request, _("Too many reminders at once. Wait a moment."))
        return back
    window = _window_of(request, department)
    offering = service.offering_in_scope(department, window, _int(request.POST.get("offering")))
    student = _int(request.POST.get("student"))
    if request.POST.get("student") and student is None:
        raise Http404
    try:
        service.queue_reminders(request, department, window, offering, student)
    except service.RemindersClosed:
        messages.error(request, _("Reminders can only be sent while the round is open."))
    else:
        messages.success(request, _("The reminder was queued."))
    return back


def _window_of(request, department):
    window_id = _int(request.POST.get("window"))
    window = next(
        (w for w in service.rounds(department, timezone.now()) if w.pk == window_id), None
    )
    if window is None:
        raise Http404
    return window


@require_GET
@role_required(HOD)
def audit(request):
    department = request.user.hod_department
    events = service.audit_events(department)
    action = request.GET.get("action", "")
    actions = sorted(set(events.values_list("action", flat=True)))
    if action in actions:
        events = events.filter(action=action)
    else:
        action = ""
    page = Paginator(events.order_by("-created_at", "-pk"), PAGE_SIZE).get_page(
        request.GET.get("page")
    )
    context = {
        "nav_items": user_nav_items(request.user, "audit"),
        "department": department,
        "page_obj": page,
        "actions": actions,
        "action": action,
        "page_query": f"{urlencode({'action': action})}&" if action else "",
    }
    return render(request, "reports/hod_audit.html", context)
