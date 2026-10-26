"""Forgot password and forgot username.

Both start with the same neutral answer ("if the details match, we sent a code") and then
ask for the code, whether or not an account exists (see ``services.otp`` decoys).
"""

from dataclasses import dataclass

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy
from django.views.decorators.http import require_http_methods, require_POST

from apps.accounts import ratelimits
from apps.accounts.auth_forms import (
    ForgotPasswordForm,
    ForgotUsernameForm,
    NewPasswordForm,
    OtpForm,
)
from apps.accounts.models import OtpPurpose
from apps.accounts.services import otp, recovery
from apps.core.permissions import public

VERIFY_ERRORS = {
    otp.VerifyStatus.WRONG: _lazy("That code is not correct."),
    otp.VerifyStatus.EXPIRED: _lazy("This code has expired. Send a new code."),
    otp.VerifyStatus.LOCKED: _lazy("Too many wrong attempts. Send a new code."),
}


@dataclass(frozen=True)
class Flow:
    session_key: str
    purpose: str
    verify_url: str
    resend_url: str
    restart_url: str
    title: str
    intro: str


PASSWORD_FLOW = Flow(
    session_key="recovery_password",
    purpose=OtpPurpose.PASSWORD_RESET,
    verify_url="accounts:password_forgot_verify",
    resend_url="accounts:password_forgot_resend",
    restart_url="accounts:password_forgot",
    title=_lazy("Reset your password"),
    intro=_lazy("Enter the code we sent to the contact on your account."),
)
USERNAME_FLOW = Flow(
    session_key="recovery_username",
    purpose=OtpPurpose.USERNAME_RECOVERY,
    verify_url="accounts:username_forgot_verify",
    resend_url="accounts:username_forgot_resend",
    restart_url="accounts:username_forgot",
    title=_lazy("Recover your username"),
    intro=_lazy("Enter the code we sent to the contact on your account."),
)

SENT_NOTICE = _lazy("If the details match an account, we sent a 6-digit code to its contact.")


def _too_many() -> str:
    return _("Too many attempts. Please wait a few minutes and try again.")


def _challenge(request, flow: Flow):
    challenge_id = request.session.get(flow.session_key)
    return otp.get_active(challenge_id, flow.purpose) if challenge_id else None


def _render_verify(request, flow: Flow, challenge, form=None, *, notice="", status=200):
    return render(
        request,
        "accounts/recovery/verify.html",
        {
            "flow": flow,
            "form": form or OtpForm(),
            "notice": notice,
            "wait": otp.seconds_until_resend(challenge),
        },
        status=status,
    )


def _render_forgot(request, form, flow: Flow, *, status: int = 200):
    return render(
        request, "accounts/recovery/forgot.html", {"form": form, "flow": flow}, status=status
    )


def _verify(request, flow: Flow, on_success):
    challenge = _challenge(request, flow)
    if challenge is None:
        return redirect(flow.restart_url)
    if request.method == "GET":
        return _render_verify(request, flow, challenge, notice=str(SENT_NOTICE))
    form = OtpForm(request.POST)
    if request.limited:
        form.add_error(None, _too_many())
        return _render_verify(request, flow, challenge, form, status=429)
    if form.is_valid():
        status, _checked = otp.verify(challenge.pk, flow.purpose, form.cleaned_data["code"])
        if status is otp.VerifyStatus.OK:
            return on_success(request, challenge)
        form.add_error("code", VERIFY_ERRORS[status])
    return _render_verify(request, flow, challenge, form)


def _resend(request, flow: Flow):
    challenge = _challenge(request, flow)
    if challenge is None:
        return redirect(flow.restart_url)
    if request.limited:
        return _render_verify(request, flow, challenge, notice=_too_many(), status=429)
    try:
        otp.resend(challenge, recovery.destination_of(challenge))
    except otp.ResendError as error:
        if error.wait:
            notice = _("Please wait %(seconds)d seconds before asking for a new code.") % {
                "seconds": error.wait
            }
        else:
            notice = _("No more codes can be sent. Start again.")
        return _render_verify(request, flow, challenge, notice=notice)
    return _render_verify(request, flow, challenge, notice=_("A new code was sent."))


# --- forgot password -------------------------------------------------------------------------


@require_http_methods(["GET", "POST"])
@ratelimits.limited(ratelimits.identifier, ip_rate="10/10m", subject_rate="4/15m")
@public
def password_forgot(request):
    form = ForgotPasswordForm(request.POST or None)
    if request.method == "POST":
        if request.limited:
            form.add_error(None, _too_many())
            return _render_forgot(request, form, PASSWORD_FLOW, status=429)
        if form.is_valid():
            challenge = recovery.start_password_reset(form.cleaned_data["identifier"])
            request.session[PASSWORD_FLOW.session_key] = str(challenge.pk)
            return redirect(PASSWORD_FLOW.verify_url)
    return _render_forgot(request, form, PASSWORD_FLOW)


def _password_verified(request, challenge):
    return redirect("accounts:password_forgot_new")


@require_http_methods(["GET", "POST"])
@ratelimits.limited(ratelimits.session_subject, ip_rate="30/10m", subject_rate="12/15m")
@public
def password_forgot_verify(request):
    return _verify(request, PASSWORD_FLOW, _password_verified)


@require_POST
@ratelimits.limited(ratelimits.session_subject, ip_rate="12/10m", subject_rate="6/15m")
@public
def password_forgot_resend(request):
    return _resend(request, PASSWORD_FLOW)


@require_http_methods(["GET", "POST"])
@ratelimits.limited(ratelimits.session_subject, ip_rate="20/10m", subject_rate="8/15m")
@public
def password_forgot_new(request):
    challenge = _challenge(request, PASSWORD_FLOW)
    if challenge is None or not otp.is_verified(challenge):
        return redirect(PASSWORD_FLOW.restart_url)
    form = NewPasswordForm(request.POST or None, user=challenge.user)
    status = 200
    if request.method == "POST":
        if request.limited:
            form.add_error(None, _too_many())
            status = 429
        elif form.is_valid():
            try:
                recovery.reset_password(challenge, form.cleaned_data["password1"], request=request)
            except ValidationError as error:
                form.add_error("password1", error)
            else:
                request.session.pop(PASSWORD_FLOW.session_key, None)
                messages.success(request, _("Your password was changed. You can log in now."))
                return redirect("accounts:login")
    return render(request, "accounts/recovery/new_password.html", {"form": form}, status=status)


# --- forgot username -------------------------------------------------------------------------


@require_http_methods(["GET", "POST"])
@ratelimits.limited(ratelimits.registry_id, ip_rate="10/10m", subject_rate="4/15m")
@public
def username_forgot(request):
    form = ForgotUsernameForm(request.POST or None)
    if request.method == "POST":
        if request.limited:
            form.add_error(None, _too_many())
            return _render_forgot(request, form, USERNAME_FLOW, status=429)
        if form.is_valid():
            challenge = recovery.start_username_recovery(form.cleaned_data["registry_id"])
            request.session[USERNAME_FLOW.session_key] = str(challenge.pk)
            return redirect(USERNAME_FLOW.verify_url)
    return _render_forgot(request, form, USERNAME_FLOW)


def _username_verified(request, challenge):
    username = recovery.recovered_username(challenge)
    request.session.pop(USERNAME_FLOW.session_key, None)
    if username is None:
        return redirect(USERNAME_FLOW.restart_url)
    return render(request, "accounts/recovery/username.html", {"username": username})


@require_http_methods(["GET", "POST"])
@ratelimits.limited(ratelimits.session_subject, ip_rate="30/10m", subject_rate="12/15m")
@public
def username_forgot_verify(request):
    return _verify(request, USERNAME_FLOW, _username_verified)


@require_POST
@ratelimits.limited(ratelimits.session_subject, ip_rate="12/10m", subject_rate="6/15m")
@public
def username_forgot_resend(request):
    return _resend(request, USERNAME_FLOW)
