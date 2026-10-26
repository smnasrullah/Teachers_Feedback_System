"""The signed-in person's profile: nickname, picture, language and theme."""

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.accounts.auth_forms import ProfileForm
from apps.accounts.models import Theme
from apps.accounts.services import account as account_service
from apps.accounts.views.account import EVERYONE, account_context
from apps.core.permissions import role_required

THEME_COOKIE = "tfs_theme"
YEAR = 365 * 24 * 60 * 60


def _remember_choices(response, request, user):
    """Make the saved language and theme win over what this browser last used."""
    response.set_cookie(
        settings.LANGUAGE_COOKIE_NAME,
        user.language,
        max_age=settings.LANGUAGE_COOKIE_AGE,
        samesite=settings.LANGUAGE_COOKIE_SAMESITE,
        secure=request.is_secure(),
    )
    if user.theme == Theme.SYSTEM:
        response.delete_cookie(THEME_COOKIE)
    else:
        response.set_cookie(
            THEME_COOKIE, user.theme, max_age=YEAR, samesite="Lax", secure=request.is_secure()
        )


@require_http_methods(["GET", "POST"])
@role_required(*EVERYONE)
def profile_edit(request):
    user = request.user
    initial = {name: getattr(user, name) for name in account_service.PROFILE_FIELDS}
    form = ProfileForm(request.POST or None, request.FILES or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        account_service.update_profile(request, user, form.cleaned_data)
        response = redirect("accounts:profile")
        messages.success(request, _("Your profile was saved."))
        _remember_choices(response, request, user)
        return response
    context = {**account_context(request, "account"), "form": form}
    return render(request, "accounts/profile.html", context)
