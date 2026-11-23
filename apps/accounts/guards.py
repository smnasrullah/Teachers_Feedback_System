"""View guards: visitors only, second-factor roles only, and a fresh password for sensitive
actions (step-up)."""

from collections.abc import Callable
from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _

from apps.accounts.services import login as login_service
from apps.accounts.services import stepup, twofactor


def guest_only(view: Callable) -> Callable:
    """Redirect a signed-in user to the dashboard of their role, whatever ``next`` says.

    A half-signed-in session (password accepted, authenticator code pending) is not
    authenticated, so it still reaches the code page and the login page.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(login_service.landing_url(request.user))
        return view(request, *args, **kwargs)

    return wrapper


def second_factor_users(view: Callable) -> Callable:
    """Authenticator management exists only for roles in ``TOTP_REQUIRED_ROLES``."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not twofactor.required_for(request.user):
            return redirect("accounts:account")
        return view(request, *args, **kwargs)

    return wrapper


def _return_path(request) -> str:
    """Where to come back after the step-up: this page, or for a form post the page it was on."""
    if request.method == "GET":
        return request.get_full_path()
    referer = request.headers.get("Referer", "")
    if url_has_allowed_host_and_scheme(
        referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return referer
    return login_service.landing_url(request.user)


def step_up_required(view: Callable) -> Callable:
    """Ask for the current password again when the last password entry is too old.

    Goes inside ``role_required``, so a role that may not use the view never sees the prompt.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if stepup.is_fresh(request):
            return view(request, *args, **kwargs)
        if request.method != "GET":
            messages.info(request, _("Confirm your password, then try again."))
        query = urlencode({"next": _return_path(request)})
        return redirect(f"{reverse('accounts:step_up')}?{query}")

    return wrapper
