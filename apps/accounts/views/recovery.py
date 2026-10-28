"""Forgot password (username + authenticator or recovery code) and forgot username (help page)."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy
from django.views.decorators.http import require_GET, require_http_methods

from apps.accounts import ratelimits
from apps.accounts.auth_forms import ForgotPasswordForm, NewPasswordForm
from apps.accounts.services import login as login_service
from apps.accounts.services import recovery
from apps.accounts.views.auth import lockout_response
from apps.core.permissions import public

GENERIC_RESET_ERROR = _lazy("The username or code is not correct.")


def _too_many() -> str:
    return _("Too many attempts. Please wait a few minutes and try again.")


@require_http_methods(["GET", "POST"])
@ratelimits.limited(ratelimits.username, ip_rate="10/10m", subject_rate="5/15m")
@public
def password_forgot(request):
    form = ForgotPasswordForm(request.POST or None)
    status = 200
    if request.method == "POST":
        if request.limited:
            form.add_error(None, _too_many())
            status = 429
        elif form.is_valid():
            username = form.cleaned_data["username"].strip().lower()
            if login_service.is_locked(request, username):
                return lockout_response(request)
            if recovery.verify(request, username, form.cleaned_data["code"]) is not None:
                return redirect("accounts:password_forgot_new")
            login_service.note_failure(request, username, stage="password_reset")
            form.add_error(None, GENERIC_RESET_ERROR)
    return render(request, "accounts/recovery/forgot.html", {"form": form}, status=status)


@require_http_methods(["GET", "POST"])
@ratelimits.limited(ratelimits.session_subject, ip_rate="20/10m", subject_rate="8/15m")
@public
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
                recovery.reset_password(request, user, form.cleaned_data["password1"])
            except ValidationError as error:
                form.add_error("password1", error)
            else:
                messages.success(request, _("Your password was changed. You can log in now."))
                return redirect("accounts:login")
    return render(request, "accounts/recovery/new_password.html", {"form": form}, status=status)


@require_GET
@public
def username_forgot(request):
    return render(request, "accounts/recovery/username.html")
