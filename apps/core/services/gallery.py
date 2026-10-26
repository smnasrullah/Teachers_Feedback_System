"""Sample data for the DEBUG-only component gallery (``/dev/gallery``)."""

from django.core.paginator import Paginator
from django.utils.translation import gettext as _


def build_gallery_context():
    nav_items = [
        {"label": _("Dashboard"), "url": "#dashboard", "icon": "home", "current": True},
        {"label": _("Courses"), "url": "#courses", "icon": "book"},
        {"label": _("Reports"), "url": "#reports", "icon": "chart"},
        {"label": _("Calendar"), "url": "#calendar", "icon": "calendar"},
        {"group": _("Manage")},
        {"label": _("Teachers"), "url": "#teachers", "icon": "users"},
        {"label": _("Settings"), "url": "#settings", "icon": "settings"},
    ]
    columns = [
        {"key": "teacher", "label": _("Teacher")},
        {"key": "course", "label": _("Course")},
        {"key": "responses", "label": _("Responses"), "numeric": True},
        {"key": "score", "label": _("Average"), "numeric": True},
    ]
    rows = [
        {"teacher": "Dr. Shirin Akter", "course": "CSE 2201", "responses": 48, "score": "4.6"},
        {"teacher": "Mr. Kamrul Hasan", "course": "CSE 2203", "responses": 44, "score": "4.2"},
        {"teacher": "Ms. Farzana Islam", "course": "EEE 2217", "responses": 39, "score": "3.9"},
    ]
    labels = [_("Teaching"), _("Content"), _("Support"), _("Fairness"), _("Clarity")]
    return {
        "nav_items": nav_items,
        "dept_options": [
            ("", _("Choose a department")),
            ("cse", "Computer Science and Engineering"),
            ("eee", "Electrical and Electronic Engineering"),
        ],
        "crumbs": [
            {"label": _("Dashboard"), "url": "#g-nav"},
            {"label": _("Reports"), "url": "#g-table"},
            {"label": _("Database Systems")},
        ],
        "empty_rows": [],
        "table_columns": columns,
        "table_rows": rows,
        "page_obj": Paginator(range(1, 101), 10).page(5),
        "bar_chart": {
            "type": "bar",
            "labels": labels,
            "datasets": [
                {"label": _("This semester"), "data": [4.6, 4.1, 3.8, 4.4, 4.0], "color": "primary"}
            ],
        },
        "radar_chart": {
            "type": "radar",
            "labels": labels,
            "datasets": [
                {"label": _("Teacher"), "data": [4.6, 4.1, 3.8, 4.4, 4.0], "color": "primary"},
                {"label": _("Department"), "data": [4.0, 4.0, 4.1, 4.2, 3.9], "color": "star"},
            ],
        },
        "trend_chart": {
            "type": "line",
            "labels": ["Spring 25", "Fall 25", "Spring 26", "Fall 26"],
            "datasets": [
                {"label": _("Average rating"), "data": [3.8, 4.0, 4.3, 4.6], "color": "success"}
            ],
        },
    }
