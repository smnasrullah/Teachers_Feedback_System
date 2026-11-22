from apps.core.services.clock import utc_iso, utc_now


def csp_nonce(request):
    return {"csp_nonce": getattr(request, "csp_nonce", "")}


def server_time(request):
    """The server's UTC time at render, for the page clock; nothing about the user."""
    return {"server_now": utc_iso(utc_now())}


def guest_auth(request):
    """``show_guest_auth_links``: whether Log in / Create account may be offered at all.

    True for an anonymous visitor and for a half-signed-in session (password accepted, the
    authenticator code still pending: no user is signed in yet). False for every signed-in
    user, and whenever the request cannot say (no user attached), so an error page never guesses.
    """
    authenticated = getattr(getattr(request, "user", None), "is_authenticated", None)
    return {"show_guest_auth_links": authenticated is False}
