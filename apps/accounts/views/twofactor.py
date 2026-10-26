"""Two-factor enrolment (forced at login, or chosen from the account page) and management."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts import ratelimits
from apps.accounts.auth_forms import ConfirmPasswordForm, TotpCodeForm
from apps.accounts.services import account as account_service
from apps.accounts.services import login as login_service
from apps.accounts.services import twofactor
from apps.accounts.views.account import EVERYONE, account_context
from apps.core.permissions import public, role_required
from apps.core.services import sessions


def _show_codes(request, codes, continue_url):
    return render(
        request,
        "accounts/recovery_codes.html",
        {**account_context(request, "account"), "codes": codes, "continue_url": continue_url},
    )


def _enrol(request, user, *, pending: bool):
    """Show the QR code and confirm the first code; ``pending`` = still finishing a login."""
    twofactor.begin_enrolment(user)
    form = TotpCodeForm(request.POST or None)
    status = 200
    if request.method == "POST":
        if request.limited:
            form.add_error(None, _("Too many attempts. Please wait a few minutes and try again."))
            status = 429
        elif form.is_valid():
            codes = account_service.enable_two_factor(request, user, form.cleaned_data["code"])
            if codes is not None:
                if pending:
                    login_service.complete_login(request, user, second_factor=True)
                else:
                    sessions.mark_second_factor(request)
                return _show_codes(request, codes, login_service.landing_url(user))
            if pending:
                login_service.note_failure(request, user.username, stage="enrolment")
            form.add_error("code", _("That code is not correct."))
    context = {
        "form": form,
        "qr": twofactor.qr_data_uri(user),
        "manual_key": twofactor.manual_key(user),
        "pending": pending,
    }
    if not pending:
        context.update(account_context(request, "account"))
    return render(request, "accounts/two_factor_setup.html", context, status=status)


@require_http_methods(["GET", "POST"])
@ratelimits.limited(ratelimits.session_subject, ip_rate="30/10m", subject_rate="10/15m")
@public
def login_two_factor_setup(request):
    user = login_service.pending_user(request)
    if user is None or user.totp_enabled or not user.requires_second_factor:
        return redirect("accounts:login")
    return _enrol(request, user, pending=True)


@require_http_methods(["GET", "POST"])
@ratelimits.limited(ratelimits.session_subject, ip_rate="30/10m", subject_rate="10/15m")
@role_required(*EVERYONE)
def account_two_factor_setup(request):
    if request.user.totp_enabled:
        return redirect("accounts:two_factor")
    return _enrol(request, request.user, pending=False)


@require_GET
@role_required(*EVERYONE)
def two_factor(request):
    user = request.user
    context = {
        **account_context(request, "account"),
        "recovery_left": twofactor.recovery_codes_left(user) if user.totp_enabled else 0,
        "must_use_two_factor": user.requires_second_factor,
        "regenerate_form": ConfirmPasswordForm(user=user),
        "disable_form": ConfirmPasswordForm(user=user),
    }
    return render(request, "accounts/two_factor.html", context)


def _confirmed(request, error_message: str):
    """The password form for a sensitive change, or ``None`` after flashing why it failed."""
    form = ConfirmPasswordForm(request.POST, user=request.user)
    if form.is_valid():
        return form
    messages.error(request, error_message)
    return None


@require_POST
@ratelimits.limited(ratelimits.session_subject, ip_rate="20/10m", subject_rate="8/15m")
@role_required(*EVERYONE)
def two_factor_regenerate(request):
    user = request.user
    if request.limited or not user.totp_enabled:
        return redirect("accounts:two_factor")
    if _confirmed(request, _("The password is not correct, so the codes were not replaced.")):
        codes = account_service.regenerate_recovery_codes(request, user)
        return _show_codes(request, codes, reverse("accounts:two_factor"))
    return redirect("accounts:two_factor")


@require_POST
@ratelimits.limited(ratelimits.session_subject, ip_rate="20/10m", subject_rate="8/15m")
@role_required(*EVERYONE)
def two_factor_disable(request):
    user = request.user
    if request.limited or not user.totp_enabled:
        return redirect("accounts:two_factor")
    if _confirmed(request, _("The password is not correct, so two-factor was not turned off.")):
        try:
            account_service.disable_two_factor(request, user)
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, _("Two-factor authentication is off."))
    return redirect("accounts:two_factor")
