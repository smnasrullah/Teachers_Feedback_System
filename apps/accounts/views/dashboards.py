"""Landing pages per role. Placeholders until each role's real dashboard is built."""

from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET

from apps.accounts.services.login import landing_url
from apps.accounts.views.account import EVERYONE
from apps.core.permissions import HOD, Role, role_required
from apps.core.services.navigation import user_nav_items


def _placeholder(request, title: str):
    return render(
        request,
        "accounts/dashboard.html",
        {"title": title, "nav_items": user_nav_items(request.user, "dashboard")},
    )


@require_GET
@role_required(*EVERYONE)
def dashboard(request):
    """Send each role to its own dashboard."""
    return redirect(landing_url(request.user))


@require_GET
@role_required(Role.TEACHER)
def dashboard_teacher(request):
    return _placeholder(request, _("Teacher dashboard"))


@require_GET
@role_required(HOD)
def dashboard_hod(request):
    return _placeholder(request, _("Head of department dashboard"))


@require_GET
@role_required(Role.ADMIN)
def dashboard_admin(request):
    return _placeholder(request, _("Admin dashboard"))
