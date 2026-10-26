"""Sidebar entries for the signed-in shell (``layouts/dashboard.html``)."""

from django.urls import reverse
from django.utils.translation import gettext as _

from apps.core.permissions import Role


def admin_nav_items(current: str = "") -> list[dict]:
    """Admin navigation; ``current`` is the ``key`` of the active entry."""
    entries = [
        {"group": _("People")},
        {
            "key": "registry",
            "label": _("ID registry"),
            "url": reverse("accounts:registry_list"),
            "icon": "list",
        },
        {
            "key": "users",
            "label": _("Users"),
            "url": reverse("accounts:user_list"),
            "icon": "users",
        },
    ]
    return [{**entry, "current": entry.get("key") == current} for entry in entries]


def user_nav_items(user, current: str = "") -> list[dict]:
    """Navigation for any signed-in role: its dashboard, the Admin screens, and the account."""
    entries = [
        {
            "key": "dashboard",
            "label": _("Dashboard"),
            "url": reverse("accounts:dashboard"),
            "icon": "home",
        }
    ]
    if getattr(user, "role", None) == Role.ADMIN:
        entries += admin_nav_items()
    entries += [
        {"group": _("Account")},
        {
            "key": "account",
            "label": _("My account"),
            "url": reverse("accounts:account"),
            "icon": "user",
        },
    ]
    return [{**entry, "current": entry.get("key") == current} for entry in entries]
