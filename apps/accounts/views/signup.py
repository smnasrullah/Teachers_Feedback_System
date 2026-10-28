"""Sign-up stepper: ID + activation code -> password -> authenticator -> recovery codes.

Each step is a partial swapped into ``#signup-step`` by HTMX; without JavaScript the same
views answer with the full page. Progress lives in the session (the claimed registry row,
the username to be, then the password hash and TOTP secret, both encrypted) and the current
step is always derived from it. Nothing is written to the account tables before the first
authenticator code checks out.
"""

from django.shortcuts import render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.accounts import ratelimits
from apps.accounts.auth_forms import ClaimForm, NewPasswordForm, TotpCodeForm
from apps.accounts.models import IdRegistry
from apps.accounts.services import signup, twofactor
from apps.core.encryption import encrypt
from apps.core.permissions import public

STATE_KEY = "signup"
STEPS = ("claim", "password", "authenticator", "done")
STEP_LABELS = (
    _lazy("ID and code"),
    _lazy("Password"),
    _lazy("Authenticator"),
    _lazy("Recovery codes"),
)
GENERIC_CLAIM_ERROR = _lazy(
    "The ID or code is not valid, or it has already been used. Check both and try again."
)


def _too_many() -> str:
    return _("Too many attempts. Please wait a few minutes and try again.")


def _state(request) -> dict:
    return request.session.get(STATE_KEY) or {}


def _save_state(request, **values) -> None:
    request.session[STATE_KEY] = {**_state(request), **values}


def _registry(request) -> IdRegistry | None:
    pk = _state(request).get("registry")
    if not pk:
        return None
    return IdRegistry.objects.select_related("department", "claimed_by").filter(pk=pk).first()


def _secret(request) -> str:
    """The authenticator secret for this sign-up (made on first view, then kept)."""
    secret = signup.unseal(_state(request).get("secret"))
    if secret is None:
        secret = twofactor.new_secret()
        _save_state(request, secret=encrypt(secret))
    return secret


def _stage(request) -> str:
    if _registry(request) is None:
        return "claim"
    if signup.unseal(_state(request).get("password")) is None:
        return "password"
    return "authenticator"


def _render(request, stage: str, context: dict | None = None, status: int = 200):
    context = {
        "stage": stage,
        "step_number": STEPS.index(stage) + 1,
        "steps": list(enumerate(STEP_LABELS, start=1)),
        **(context or {}),
    }
    template = f"accounts/signup/_{stage}.html"
    if request.headers.get("HX-Request"):
        return render(request, template, context, status=status)
    return render(
        request,
        "accounts/signup/page.html",
        {**context, "step_template": template},
        status=status,
    )


def _current(request, context: dict | None = None, status: int = 200):
    stage = _stage(request)
    context = dict(context or {})
    if stage == "authenticator":
        secret = _secret(request)
        username = _state(request)["username"]
        context.setdefault("form", TotpCodeForm())
        context["qr"] = twofactor.qr_data_uri(secret, username)
        context["manual_key"] = twofactor.manual_key(secret)
        context["username"] = username
    elif stage == "password":
        context.setdefault("form", NewPasswordForm())
    else:
        context.setdefault("form", ClaimForm())
    return _render(request, stage, context, status)


def _restart(request) -> None:
    request.session.pop(STATE_KEY, None)


@require_http_methods(["GET", "POST"])
@ratelimits.limited(ratelimits.registry_id, ip_rate="30/10m", subject_rate="8/15m")
@public
def signup_claim(request):
    if request.method == "GET":
        if request.GET.get("restart"):
            _restart(request)
        return _current(request)
    form = ClaimForm(request.POST)
    if request.limited:
        form.add_error(None, _too_many())
        return _render(request, "claim", {"form": form}, status=429)
    if form.is_valid():
        registry = signup.find_claimable(
            form.cleaned_data["registry_id"], form.cleaned_data["activation_code"]
        )
        if registry is not None:
            request.session[STATE_KEY] = {
                "registry": registry.pk,
                "username": signup.username_for(registry),
            }
            return _current(request)
        form.add_error(None, GENERIC_CLAIM_ERROR)
    return _render(request, "claim", {"form": form})


@require_http_methods(["GET", "POST"])
@ratelimits.limited(ratelimits.session_subject, ip_rate="20/10m", subject_rate="8/15m")
@public
def signup_password(request):
    registry = _registry(request)
    if request.method == "GET" or registry is None:
        return _current(request)
    form = NewPasswordForm(request.POST, user=registry.claimed_by, role=signup.role_for(registry))
    if request.limited:
        form.add_error(None, _too_many())
        return _render(request, "password", {"form": form}, status=429)
    if form.is_valid():
        password_hash = signup.hash_password(form.cleaned_data["password1"])
        _save_state(request, password=encrypt(password_hash))
        return _current(request)
    return _render(request, "password", {"form": form})


@require_http_methods(["GET", "POST"])
@ratelimits.limited(ratelimits.session_subject, ip_rate="30/10m", subject_rate="12/15m")
@never_cache
@public
def signup_authenticator(request):
    registry = _registry(request)
    password_hash = signup.unseal(_state(request).get("password"))
    if request.method == "GET" or registry is None or password_hash is None:
        return _current(request)
    form = TotpCodeForm(request.POST)
    if request.limited:
        form.add_error(None, _too_many())
        return _current(request, {"form": form}, status=429)
    if not form.is_valid():
        return _current(request, {"form": form})
    try:
        result = signup.complete(
            registry.pk,
            username=_state(request)["username"],
            password_hash=password_hash,
            secret=_secret(request),
            code=form.cleaned_data["code"],
            request=request,
        )
    except signup.SignupError:
        _restart(request)
        notice = _("Sign-up could not be completed. Please start again.")
        return _render(request, "claim", {"form": ClaimForm(), "error": notice})
    if result is None:
        form.add_error("code", _("That code is not correct. Check the time on your phone."))
        return _current(request, {"form": form})
    user, codes = result
    _restart(request)
    return _render(request, "done", {"username": user.username, "codes": codes, "done": True})
