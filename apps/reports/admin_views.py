"""The Admin's home and university analytics. Both are Admin-only; every query is university
wide by design and the figures themselves are held back by ``apps.analytics``."""

from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.core.permissions import Role, role_required
from apps.core.services.navigation import admin_nav_items
from apps.reports.forms import UniversityFilterForm
from apps.reports.services import admin_home, university


@require_GET
@role_required(Role.ADMIN)
def home(request):
    now = timezone.now()
    context = {
        "nav_items": admin_nav_items("dashboard"),
        "home": admin_home.build(request.user, now),
    }
    return render(request, "admin_panel/home.html", context)


@require_GET
@role_required(Role.ADMIN)
def analytics(request):
    now = timezone.now()
    form = UniversityFilterForm(request.GET or None)
    criteria = form.cleaned_data if form.is_valid() else {}
    available = university.rounds(criteria.get("semester"), now)
    window = university.pick_round(available, criteria.get("round"), now)
    context = {
        "nav_items": admin_nav_items("analytics"),
        "form": form,
        "window": window,
        "report": None,
    }
    if window is not None:
        filters = university.Filters(
            criteria.get("semester"),
            criteria.get("department"),
            criteria.get("level_term"),
            window,
        )
        report = university.build(filters, request.user, now)
        context |= {
            "report": report,
            "distribution_chart": university.distribution_chart(report.distribution),
            "department_chart": university.department_chart(report.departments),
            "round_open": window.is_open(now),
            "closes_at": window.closes_at,
        }
    return render(request, "admin_panel/analytics.html", context)
