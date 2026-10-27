"""Login, second factor and logout."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, logout
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy
from django.views.decorators.http import require_http_methods, require_POST

from apps.accounts import ratelimits
from apps.accounts.auth_forms import LoginForm, SecondFactorForm
from apps.accounts.services import login as login_service
from apps.accounts.services import twofactor
from apps.core.permissions import public
from apps.core.services.demo import constants as demo_constants

GENERIC_LOGIN_ERROR = _lazy("The username or password is not correct.")


def _too_many_message() -> str:
    return _("Too many attempts. Please wait a few minutes and try again.")


def lockout_response(request, response=None, credentials=None):
    """``AXES_LOCKOUT_CALLABLE``: the same answer for known and unknown usernames."""
    minutes = int(settings.AXES_COOLOFF_TIME.total_seconds() // 60)
    error = _("Too many failed attempts. Please try again in %(minutes)d minutes.") % {
        "minutes": minutes
    }
    context = {"form": LoginForm(), "next": "", "error": error}
    return render(request, "accounts/login.html", context, status=429)


@require_http_methods(["GET", "POST"])
@ratelimits.limited(ratelimits.username, ip_rate="30/10m", subject_rate="10/15m")
@public
def login_view(request):
    if request.user.is_authenticated:
        return redirect(login_service.landing_url(request.user))
    form = LoginForm(request.POST or None)
    status = 200
    if request.method == "POST":
        if request.limited:
            form.add_error(None, _too_many_message())
            status = 429
        elif form.is_valid():
            username = form.cleaned_data["username"].strip().lower()
            user = authenticate(request, username=username, password=form.cleaned_data["password"])
            if user is not None:
                return _after_password(request, user)
            login_service.note_failure(request, username, stage="password")
            form.add_error(None, GENERIC_LOGIN_ERROR)
    context = {
        "form": form,
        "next": login_service.safe_next(request) or "",
        "demo_usernames": demo_constants.USERNAMES if settings.DEBUG else (),
    }
    return render(request, "accounts/login.html", context, status=status)


def _after_password(request, user):
    if login_service.is_demo_account(request, user):
        next_url = login_service.safe_next(request)
        login_service.complete_demo_login(request, user)
        return redirect(next_url or login_service.landing_url(user))
    login_service.begin_pending(request, user, login_service.safe_next(request))
    if login_service.next_step(user) is login_service.NextStep.CODE:
        return redirect("accounts:login_second_factor")
    return redirect("accounts:login_two_factor_setup")


@require_http_methods(["GET", "POST"])
@ratelimits.limited(ratelimits.session_subject, ip_rate="30/10m", subject_rate="10/15m")
@public
def login_second_factor(request):
    user = login_service.pending_user(request)
    if user is None or not user.totp_enabled:
        return redirect("accounts:login")
    form = SecondFactorForm(request.POST or None)
    status = 200
    if request.method == "POST":
        if request.limited:
            form.add_error(None, _too_many_message())
            status = 429
        elif login_service.is_locked(request, user.username):
            return lockout_response(request)
        elif form.is_valid():
            result = twofactor.check_second_factor(user, form.cleaned_data["code"])
            if result.ok:
                next_url = login_service.pending_next(request)
                login_service.complete_login(request, user)
                if result.recovery:
                    login_service.record_recovery_use(request, user, result.recovery_left)
                    messages.warning(
                        request,
                        _("You signed in with a recovery code. %(left)d recovery codes are left.")
                        % {"left": result.recovery_left},
                    )
                return redirect(next_url or login_service.landing_url(user))
            login_service.note_failure(request, user.username, stage="second_factor")
            form.add_error(None, _("That code is not correct."))
    return render(request, "accounts/second_factor.html", {"form": form}, status=status)


@require_POST
@public
def logout_view(request):
    logout(request)
    messages.info(request, _("You have been logged out."))
    return redirect("accounts:login")
