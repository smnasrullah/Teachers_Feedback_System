"""Views for visitors only: a fully signed-in user is sent to their own dashboard."""

from collections.abc import Callable
from functools import wraps

from django.shortcuts import redirect

from apps.accounts.services import login as login_service


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
