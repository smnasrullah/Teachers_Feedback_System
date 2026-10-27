"""The landing redirect. Each role's dashboard lives in the app that owns its data."""

from django.shortcuts import redirect
from django.views.decorators.http import require_GET

from apps.accounts.services.login import landing_url
from apps.accounts.views.account import EVERYONE
from apps.core.permissions import role_required


@require_GET
@role_required(*EVERYONE)
def dashboard(request):
    """Send each role to its own dashboard."""
    return redirect(landing_url(request.user))
