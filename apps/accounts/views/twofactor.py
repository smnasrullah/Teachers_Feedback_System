"""Authenticator enrolment at login (accounts without one yet) and its management.

Every account signs in with an authenticator app. From the account page a person can see how
many recovery codes are left, make new ones, or move to a new phone; both changes need the
password and a current code.
"""

from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts import ratelimits
from apps.accounts.auth_forms import ReauthForm, TotpCodeForm
from apps.accounts.services import account as account_service
from apps.accounts.services import login as login_service
from apps.accounts.services import twofactor
from apps.accounts.views.account import EVERYONE, account_context
from apps.core.permissions import public, role_required

REAUTH_FAILED = _lazy("The password or code is not correct.")


def _too_many() -> str:
    return _("Too many attempts. Please wait a few minutes and try again.")


def _show_codes(request, codes, continue_url):
    """The new recovery codes, shown this once (the person is signed in by now)."""
    context = {**account_context(request, "account"), "codes": codes, "continue_url": continue_url}
    return render(request, "accounts/recovery_codes.html", context)


@require_http_methods(["GET", "POST"])
@ratelimits.limited(ratelimits.session_subject, ip_rate="30/10m", subject_rate="10/15m")
@never_cache
@public
def login_two_factor_setup(request):
    """An account without an authenticator (made before it was required) enrols at login."""
    user = login_service.pending_user(request)
    if user is None or user.totp_enabled:
        return redirect("accounts:login")
    secret = twofactor.begin_enrolment(user)
    form = TotpCodeForm(request.POST or None)
    status = 200
    if request.method == "POST":
        if request.limited:
            form.add_error(None, _too_many())
            status = 429
        elif form.is_valid():
            codes = account_service.enable_two_factor(request, user, form.cleaned_data["code"])
            if codes is not None:
                login_service.complete_login(request, user)
                return _show_codes(request, codes, login_service.landing_url(user))
            login_service.note_failure(request, user.username, stage="enrolment")
            form.add_error("code", _("That code is not correct. Check the time on your phone."))
    context = {
        "form": form,
        "qr": twofactor.qr_data_uri(secret, user.username),
        "manual_key": twofactor.manual_key(secret),
        "username": user.username,
    }
    return render(request, "accounts/two_factor_setup.html", context, status=status)


@require_GET
@role_required(*EVERYONE)
def two_factor(request):
    user = request.user
    context = {
        **account_context(request, "account"),
        "recovery_left": twofactor.recovery_codes_left(user),
        "regenerate_form": ReauthForm(prefix="regenerate"),
        "device_form": ReauthForm(prefix="device"),
    }
    return render(request, "accounts/two_factor.html", context)


def _reauthenticated(request, prefix: str) -> bool:
    """Password and current code for a sensitive change; flashes why when it fails."""
    form = ReauthForm(request.POST, prefix=prefix)
    if request.limited:
        messages.error(request, _too_many())
        return False
    data = form.cleaned_data if form.is_valid() else None
    if data and account_service.reauthenticate(request.user, data["password"], data["code"]):
        return True
    messages.error(request, REAUTH_FAILED)
    return False


@require_POST
@ratelimits.limited(ratelimits.session_subject, ip_rate="20/10m", subject_rate="8/15m")
@never_cache
@role_required(*EVERYONE)
def two_factor_regenerate(request):
    if not _reauthenticated(request, "regenerate"):
        return redirect("accounts:two_factor")
    codes = account_service.regenerate_recovery_codes(request, request.user)
    return _show_codes(request, codes, reverse("accounts:two_factor"))


@require_POST
@ratelimits.limited(ratelimits.session_subject, ip_rate="20/10m", subject_rate="8/15m")
@role_required(*EVERYONE)
def two_factor_device(request):
    if not _reauthenticated(request, "device"):
        return redirect("accounts:two_factor")
    account_service.start_device_change(request)
    return redirect("accounts:two_factor_device_confirm")


@require_http_methods(["GET", "POST"])
@ratelimits.limited(ratelimits.session_subject, ip_rate="30/10m", subject_rate="10/15m")
@never_cache
@role_required(*EVERYONE)
def two_factor_device_confirm(request):
    user = request.user
    secret = account_service.pending_device_secret(request)
    if secret is None:
        return redirect("accounts:two_factor")
    form = TotpCodeForm(request.POST or None)
    status = 200
    if request.method == "POST":
        if request.limited:
            form.add_error(None, _too_many())
            status = 429
        elif form.is_valid():
            if account_service.finish_device_change(request, user, form.cleaned_data["code"]):
                messages.success(request, _("Your new authenticator is set up."))
                return redirect("accounts:two_factor")
            form.add_error("code", _("That code is not correct. Check the time on your phone."))
    context = {
        **account_context(request, "account"),
        "form": form,
        "qr": twofactor.qr_data_uri(secret, user.username),
        "manual_key": twofactor.manual_key(secret),
    }
    return render(request, "accounts/two_factor_device.html", context, status=status)
