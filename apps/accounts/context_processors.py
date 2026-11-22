from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

from apps.accounts.services import login as login_service
from apps.core.permissions import ROLE_LABELS, primary_role


def account_menu(request):
    """The signed-in header: who is signed in, their role, own dashboard, account links, log out.

    The name is the nickname or the generated username, never a student or registry ID.
    """
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return {"account_name": ""}
    return {
        "account_name": user.nickname or user.get_username(),
        "account_role": ROLE_LABELS.get(primary_role(user), ""),
        "dashboard_url": login_service.landing_url(user),
        "user_menu": [
            {"label": _("My account"), "url": reverse_lazy("accounts:account"), "icon": "user"}
        ],
        "logout_url": reverse_lazy("accounts:logout"),
    }
