"""Confirm the current password before a sensitive action (see ``guards.step_up_required``)."""

from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.accounts import ratelimits
from apps.accounts.auth_forms import StepUpForm
from apps.accounts.services import login as login_service
from apps.accounts.services import stepup
from apps.accounts.views.account import EVERYONE, account_context
from apps.core.permissions import role_required


@require_http_methods(["GET", "POST"])
@never_cache
@ratelimits.limited(ratelimits.session_subject, ip_rate="20/10m", subject_rate="8/15m")
@role_required(*EVERYONE)
def step_up(request):
    next_url = login_service.safe_next(request) or login_service.landing_url(request.user)
    form = StepUpForm(request.POST or None)
    status = 200
    if request.method == "POST":
        if request.limited:
            form.add_error(None, _("Too many attempts. Please wait a few minutes and try again."))
            status = 429
        elif form.is_valid():
            outcome = stepup.confirm(request, form.cleaned_data["password"])
            if outcome == stepup.StepUpOutcome.OK:
                return redirect(next_url)
            if outcome == stepup.StepUpOutcome.LOCKED:
                form.add_error(None, _("Too many failed attempts. Please try again later."))
                status = 429
            else:
                form.add_error("password", _("The password is not correct."))
    context = {**account_context(request, ""), "form": form, "next": next_url}
    return render(request, "accounts/step_up.html", context, status=status)
