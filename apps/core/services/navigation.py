"""Sidebar entries for the signed-in shell (``layouts/dashboard.html``)."""

from django.urls import reverse
from django.utils.translation import gettext as _


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
