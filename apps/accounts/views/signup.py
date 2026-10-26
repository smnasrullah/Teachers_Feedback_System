"""Sign-up stepper: ID + activation code -> contact -> OTP -> password.

Each step is a partial swapped into ``#signup-step`` by HTMX; without JavaScript the same
views answer with the full page. Progress lives in the session as the claimed registry row
and the OTP challenge, and the current step is always derived from them.
"""

from django.core.exceptions import ValidationError
from django.shortcuts import render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy
from django.views.decorators.http import require_http_methods

from apps.accounts import ratelimits
from apps.accounts.auth_forms import ClaimForm, ContactForm, NewPasswordForm, OtpForm
from apps.accounts.models import IdRegistry, IdType, OtpPurpose
from apps.accounts.services import otp, signup
from apps.core.permissions import Role, public

STATE_KEY = "signup"
STEPS = ("claim", "contact", "verify", "password")
STEP_LABELS = (
    _lazy("ID and code"),
    _lazy("Contact"),
    _lazy("Verify"),
    _lazy("Password"),
)
GENERIC_CLAIM_ERROR = _lazy(
    "The ID or code is not valid, or it has already been used. Check both and try again."
)


VERIFY_ERRORS = {
    otp.VerifyStatus.WRONG: _lazy("That code is not correct."),
    otp.VerifyStatus.EXPIRED: _lazy("This code has expired. Send a new code."),
    otp.VerifyStatus.LOCKED: _lazy("Too many wrong attempts. Send a new code."),
}


def _too_many() -> str:
    return _("Too many attempts. Please wait a few minutes and try again.")


def _registry(request) -> IdRegistry | None:
    pk = (request.session.get(STATE_KEY) or {}).get("registry")
    return IdRegistry.objects.select_related("department").filter(pk=pk).first() if pk else None


def _challenge(request):
    challenge_id = (request.session.get(STATE_KEY) or {}).get("challenge")
    return otp.get_active(challenge_id, OtpPurpose.SIGNUP) if challenge_id else None


def _stage(request) -> str:
    if _registry(request) is None:
        return "claim"
    challenge = _challenge(request)
    if challenge is None:
        return "contact"
    return "password" if otp.is_verified(challenge) else "verify"


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
    if stage == "verify":
        challenge = _challenge(request)
        context.setdefault("form", OtpForm())
        context["wait"] = otp.seconds_until_resend(challenge)
        context["channel"] = challenge.channel
    elif stage == "contact":
        context.setdefault("form", ContactForm())
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
            request.session[STATE_KEY] = {"registry": registry.pk}
            return _current(request)
        form.add_error(None, GENERIC_CLAIM_ERROR)
    return _render(request, "claim", {"form": form})


@require_http_methods(["GET", "POST"])
@ratelimits.limited(ratelimits.session_subject, ip_rate="12/10m", subject_rate="6/15m")
@public
def signup_contact(request):
    registry = _registry(request)
    if registry is None:
        return _current(request)
    if request.method == "GET":
        return _render(request, "contact", {"form": ContactForm()})
    form = ContactForm(request.POST)
    if request.limited:
        form.add_error(None, _too_many())
        return _render(request, "contact", {"form": form}, status=429)
    if form.is_valid():
        try:
            challenge = signup.start_verification(registry, form.cleaned_data["contact"])
        except ValidationError as error:
            form.add_error("contact", error)
        else:
            request.session[STATE_KEY] = {"registry": registry.pk, "challenge": str(challenge.pk)}
            return _current(request)
    return _render(request, "contact", {"form": form})


@require_http_methods(["GET", "POST"])
@ratelimits.limited(ratelimits.session_subject, ip_rate="30/10m", subject_rate="12/15m")
@public
def signup_verify(request):
    challenge = _challenge(request)
    if request.method == "GET" or challenge is None:
        return _current(request)
    form = OtpForm(request.POST)
    if request.limited:
        form.add_error(None, _too_many())
        return _current(request, {"form": form}, status=429)
    if form.is_valid():
        status, _checked = otp.verify(challenge.pk, OtpPurpose.SIGNUP, form.cleaned_data["code"])
        if status is otp.VerifyStatus.OK:
            return _current(request)
        form.add_error("code", VERIFY_ERRORS[status])
    return _current(request, {"form": form})


@require_http_methods(["POST"])
@ratelimits.limited(ratelimits.session_subject, ip_rate="12/10m", subject_rate="6/15m")
@public
def signup_resend(request):
    challenge = _challenge(request)
    if challenge is None:
        return _current(request)
    if request.limited:
        return _current(request, {"notice": _too_many()}, status=429)
    try:
        otp.resend(challenge, challenge.destination)
    except otp.ResendError as error:
        if error.wait:
            notice = _("Please wait %(seconds)d seconds before asking for a new code.") % {
                "seconds": error.wait
            }
        else:
            notice = _("No more codes can be sent. Start again.")
        return _current(request, {"notice": notice})
    return _current(request, {"notice": _("A new code was sent.")})


@require_http_methods(["GET", "POST"])
@ratelimits.limited(ratelimits.session_subject, ip_rate="20/10m", subject_rate="8/15m")
@public
def signup_password(request):
    registry = _registry(request)
    challenge = _challenge(request)
    if registry is None or challenge is None or not otp.is_verified(challenge):
        return _current(request)
    if request.method == "GET":
        return _current(request)
    role = Role.STUDENT if registry.id_type == IdType.STUDENT else Role.TEACHER
    form = NewPasswordForm(request.POST, role=role)
    if request.limited:
        form.add_error(None, _too_many())
        return _current(request, {"form": form}, status=429)
    if form.is_valid():
        try:
            user = signup.create_account(
                registry.pk, challenge.pk, form.cleaned_data["password1"], request=request
            )
        except signup.SignupError:
            _restart(request)
            notice = _("Sign-up could not be completed. Please start again.")
            return _render(request, "claim", {"form": ClaimForm(), "error": notice})
        _restart(request)
        return _render(request, "password", {"username": user.username, "done": True})
    return _current(request, {"form": form})
