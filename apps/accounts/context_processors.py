from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _


def account_menu(request):
    """Account links and the log-out form for the navbar of every signed-in page."""
    if not getattr(getattr(request, "user", None), "is_authenticated", False):
        return {}
    return {
        "user_menu": [
            {"label": _("My account"), "url": reverse_lazy("accounts:account"), "icon": "user"}
        ],
        "logout_url": reverse_lazy("accounts:logout"),
    }
