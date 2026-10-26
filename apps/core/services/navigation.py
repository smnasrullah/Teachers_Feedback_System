"""Sidebar entries for the signed-in shell (``layouts/dashboard.html``)."""

from django.urls import reverse
from django.utils.translation import gettext as _

from apps.academics.screens import SCREENS
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
        {"group": _("Academics")},
        *(
            {
                "key": f"academics-{screen.key}",
                "label": screen.title,
                "url": reverse("academics:list", kwargs={"entity": screen.key}),
                "icon": screen.icon,
            }
            for screen in SCREENS.values()
        ),
        {
            "key": "assign",
            "label": _("Assign teachers"),
            "url": reverse("academics:assign_teachers"),
            "icon": "users",
        },
        {"group": _("Enrollment")},
        {
            "key": "enroll-group",
            "label": _("Enroll by level/term"),
            "url": reverse("enrollment:group"),
            "icon": "users",
        },
        {
            "key": "enrollments",
            "label": _("Enrollments"),
            "url": reverse("enrollment:list"),
            "icon": "list",
        },
        {
            "key": "enroll-missing",
            "label": _("Missing enrollment"),
            "url": reverse("enrollment:missing"),
            "icon": "list",
        },
        {"group": _("Results")},
        {
            "key": "results",
            "label": _("Results"),
            "url": reverse("academics:results"),
            "icon": "file",
        },
        {
            "key": "promotion",
            "label": _("Promotion"),
            "url": reverse("academics:promotion"),
            "icon": "award",
        },
        {
            "key": "promotion-rule",
            "label": _("Promotion rule"),
            "url": reverse("academics:promotion_rule"),
            "icon": "settings",
        },
        {"group": _("Feedback")},
        {
            "key": "questions",
            "label": _("Questions"),
            "url": reverse("feedback:questions"),
            "icon": "list",
        },
        {
            "key": "categories",
            "label": _("Question categories"),
            "url": reverse("feedback:categories"),
            "icon": "list",
        },
        {
            "key": "filter-terms",
            "label": _("Filter words"),
            "url": reverse("feedback:filter_terms"),
            "icon": "settings",
        },
        {
            "key": "flagged",
            "label": _("Flagged comments"),
            "url": reverse("feedback:flagged"),
            "icon": "flag",
        },
        {
            "key": "windows",
            "label": _("Feedback rounds"),
            "url": reverse("feedback:windows"),
            "icon": "calendar",
        },
        {"group": _("Data")},
        {
            "key": "import",
            "label": _("CSV import"),
            "url": reverse("academics:import_index"),
            "icon": "list",
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
