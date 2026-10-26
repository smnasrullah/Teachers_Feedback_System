"""The Admin's system settings page."""

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.core.forms import SystemSettingsForm
from apps.core.permissions import Role, role_required
from apps.core.services import system_settings
from apps.core.services.navigation import admin_nav_items


@require_http_methods(["GET", "POST"])
@role_required(Role.ADMIN)
def settings_page(request):
    form = SystemSettingsForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        changed = system_settings.update(form.cleaned_data, actor=request.user, request=request)
        messages.success(request, _("Settings saved.") if changed else _("Nothing was changed."))
        return redirect("core:settings")
    return render(
        request,
        "admin_panel/settings.html",
        {"nav_items": admin_nav_items("settings"), "form": form},
    )
