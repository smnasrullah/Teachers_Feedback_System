from apps.core.services.clock import utc_iso, utc_now


def csp_nonce(request):
    return {"csp_nonce": getattr(request, "csp_nonce", "")}


def server_time(request):
    """The server's UTC time at render, for the page clock; nothing about the user."""
    return {"server_now": utc_iso(utc_now())}
