import logging
import re
import secrets
import uuid

from django.contrib import messages
from django.contrib.auth import logout
from django.core.exceptions import PermissionDenied
from django.utils.cache import add_never_cache_headers, patch_vary_headers
from django.utils.translation import gettext_lazy as _

from .logging import request_id_var
from .permissions import access_policy_of, is_exempt
from .services import sessions

logger = logging.getLogger(__name__)

CSP_TEMPLATE = (
    "default-src 'self'; "
    "script-src 'self' 'nonce-{nonce}'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)
PERMISSIONS_POLICY = (
    "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), "
    "microphone=(), payment=(), usb=(), fullscreen=(self)"
)
REQUEST_ID_HEADER = "X-Request-ID"
_INCOMING_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestIdMiddleware:
    """Tag the request, its log lines and the response with one id.

    A well-formed ``X-Request-ID`` from the proxy is kept for end-to-end tracing.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request.request_id = (
            incoming if _INCOMING_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        )
        token = request_id_var.set(request.request_id)
        try:
            response = self.get_response(request)
        finally:
            request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = request.request_id
        return response


class SecurityHeadersMiddleware:
    """CSP with a per-request nonce, Permissions-Policy, and no caching of signed-in pages.

    HSTS, X-Frame-Options, Referrer-Policy and nosniff come from Django's own middleware
    (configured in settings, verified by ``check --deploy``).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.csp_nonce = secrets.token_urlsafe(16)
        response = self.get_response(request)
        response.headers.setdefault(
            "Content-Security-Policy", CSP_TEMPLATE.format(nonce=request.csp_nonce)
        )
        response.headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            add_never_cache_headers(response)
            patch_vary_headers(response, ("Cookie",))
        return response


class SessionSecurityMiddleware:
    """End sessions that are idle, past their absolute lifetime, or replaced by a newer login."""

    notices = {
        sessions.SessionProblem.IDLE: _("You were signed out after a period of inactivity."),
        sessions.SessionProblem.EXPIRED: _("Your session has expired. Please sign in again."),
        sessions.SessionProblem.REPLACED: _(
            "You were signed out because your account signed in on another device."
        ),
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            problem = sessions.problem(request)
            if problem is None:
                sessions.touch(request)
            else:
                logout(request)
                messages.info(request, self.notices[problem])
        return self.get_response(request)


class AccessPolicyMiddleware:
    """Deny by default: a view without a declared access policy is never served."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if access_policy_of(view_func) is not None or is_exempt(match.view_name, match.namespaces):
            return None
        logger.error("View %s has no access policy; request denied.", match.view_name)
        raise PermissionDenied
