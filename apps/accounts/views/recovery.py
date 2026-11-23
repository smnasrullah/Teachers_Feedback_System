"""Forgot password (registry ID + one-time reset code) and forgot username (help page)."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from apps.accounts import ratelimits
from apps.accounts.auth_forms import ForgotPasswordForm, NewPasswordForm
from apps.accounts.guards import guest_only
from apps.accounts.services import login as login_service
from apps.accounts.services import recovery
from apps.accounts.views.auth import lockout_response
from apps.core.permissions import public

GENERIC_RESET_ERROR = _lazy("The ID or reset code is not valid, or it has already been used.")


def _too_many() -> str:
    return _("Too many attempts. Please wait a few minutes and try again.")


@require_http_methods(["GET", "POST"])
@never_cache
@ratelimits.limited(ratelimits.registry_id, ip_rate="10/10m", subject_rate="5/15m")
@public
@guest_only
def password_forgot(request):
    form = ForgotPasswordForm(request.POST or None)
    status = 200
    if request.method == "POST":
        if request.limited:
            form.add_error(None, _too_many())
            status = 429
        elif form.is_valid():
            registry_id = form.cleaned_data["registry_id"]
            # django-axes counts failures under a hash, so no student ID reaches its log lines.
            subject = recovery.lockout_subject(registry_id)
            if login_service.is_locked(request, subject):
                return lockout_response(request)
            if recovery.verify(request, registry_id, form.cleaned_data["reset_code"]) is not None:
                return redirect("accounts:password_forgot_new")
            login_service.note_failure(request, subject, stage="password_reset")
            form.add_error(None, GENERIC_RESET_ERROR)
    return render(request, "accounts/recovery/forgot.html", {"form": form}, status=status)


@require_http_methods(["GET", "POST"])
@never_cache
@ratelimits.limited(ratelimits.session_subject, ip_rate="20/10m", subject_rate="8/15m")
@public
@guest_only
def password_forgot_new(request):
    user = recovery.pending_user(request)
    if user is None:
        return redirect("accounts:password_forgot")
    form = NewPasswordForm(request.POST or None, user=user)
    status = 200
    if request.method == "POST":
        if request.limited:
            form.add_error(None, _too_many())
            status = 429
        elif form.is_valid():
            try:
                recovery.reset_password(request, form.cleaned_data["password1"])
            except ValidationError as error:
                if error.code == "expired":
                    messages.error(request, error.messages[0])
                    return redirect("accounts:password_forgot")
                form.add_error("password1", error)
            else:
                messages.success(request, _("Your password was changed. You can log in now."))
                return redirect("accounts:login")
    return render(request, "accounts/recovery/new_password.html", {"form": form}, status=status)


@require_GET
@never_cache
@public
@guest_only
def username_forgot(request):
    return render(request, "accounts/recovery/username.html")
