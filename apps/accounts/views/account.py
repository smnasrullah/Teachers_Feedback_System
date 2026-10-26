"""The signed-in person's own account: username, password, sessions."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts import ratelimits
from apps.accounts.auth_forms import PasswordChangeForm
from apps.accounts.services import account as account_service
from apps.core.permissions import ALL_ROLES, role_required
from apps.core.services.navigation import user_nav_items

EVERYONE = tuple(sorted(ALL_ROLES))


def account_context(request, current: str) -> dict:
    return {"nav_items": user_nav_items(request.user, current)}


@require_GET
@role_required(*EVERYONE)
def account_home(request):
    user = request.user
    context = {
        **account_context(request, "account"),
        "sessions": account_service.active_sessions(user),
        "must_use_two_factor": user.requires_second_factor,
    }
    return render(request, "accounts/account.html", context)


@require_http_methods(["GET", "POST"])
@ratelimits.limited(ratelimits.session_subject, ip_rate="20/10m", subject_rate="8/15m")
@role_required(*EVERYONE)
def password_change(request):
    form = PasswordChangeForm(request.POST or None, user=request.user)
    status = 200
    if request.method == "POST":
        if request.limited:
            form.add_error(None, _("Too many attempts. Please wait a few minutes and try again."))
            status = 429
        elif form.is_valid():
            try:
                account_service.change_password(
                    request, request.user, form.cleaned_data["password1"]
                )
            except ValidationError as error:
                form.add_error("password1", error)
            else:
                messages.success(request, _("Your password was changed."))
                return redirect("accounts:account")
    context = {**account_context(request, "account"), "form": form}
    return render(request, "accounts/password_change.html", context, status=status)


@require_POST
@role_required(*EVERYONE)
def sign_out_everywhere(request):
    account_service.sign_out_everywhere(request, request.user)
    messages.info(request, _("You were signed out on every device."))
    return redirect("accounts:login")
