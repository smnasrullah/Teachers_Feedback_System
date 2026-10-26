import ipaddress

from django.conf import settings

UNKNOWN_IP = "0.0.0.0"  # noqa: S104 - placeholder value, never bound


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(request) -> str:
    """Client address, trusting ``X-Forwarded-For`` only for ``TRUSTED_PROXY_COUNT`` hops.

    Each trusted proxy appends the address it saw, so the client is the N-th entry from
    the right; anything further left is client-controlled and ignored. Used by audit,
    django-axes and django-ratelimit so all three agree on who the client is.
    """
    proxies = settings.TRUSTED_PROXY_COUNT
    if proxies > 0:
        hops = [
            hop for hop in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if hop.strip()
        ]
        if len(hops) >= proxies:
            forwarded = _valid_ip(hops[-proxies])
            if forwarded:
                return forwarded
    return _valid_ip(request.META.get("REMOTE_ADDR", "")) or UNKNOWN_IP
