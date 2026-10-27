"""Every GET route, as every role, on the demo data: the status BLUEPRINT §5.3 allows, no 500,
and every page renders cleanly in English and Bangla.

Columns: anonymous, demo_student, demo_teacher, demo_hod, demo_admin. ``LOGIN`` is the redirect
to the login page; a POST-only route answers a GET with 405.
"""

import copy

import pytest
from django.urls import reverse

from apps.academics.models import Department
from apps.accounts.models import User
from apps.core.services.demo import constants as demo
from tests.qa.conftest import ROLES, all_routes, client_for, sample_kwargs
from tests.qa.pages import INVALID, leaks, untranslated

LOGIN = "login"
PUBLIC = (200,) * 5
SIGNED_IN = (LOGIN, 200, 200, 200, 200)
ADMIN = (LOGIN, 403, 403, 403, 200)
POST_ONLY = (405,) * 5
REDIRECT = (302,) * 5
# Any answer but a server error: Django's own admin decides the rest for its Admin user.
ANSWERS = "answers"
DJANGO_ADMIN = (302, 302, 302, 302, ANSWERS)

EXPECTED = {
    "set_language": REDIRECT,
    "accounts:login": (200, 302, 302, 302, 302),
    "accounts:login_second_factor": REDIRECT,
    "accounts:login_two_factor_setup": REDIRECT,
    "accounts:logout": POST_ONLY,
    "accounts:signup": PUBLIC,
    "accounts:signup_password": PUBLIC,
    "accounts:signup_authenticator": PUBLIC,
    "accounts:password_forgot": PUBLIC,
    "accounts:password_forgot_new": REDIRECT,
    "accounts:username_forgot": PUBLIC,
    "accounts:dashboard": REDIRECT,
    "accounts:dashboard_student": (LOGIN, 200, 403, 403, 403),
    "accounts:dashboard_teacher": (LOGIN, 403, 200, 200, 403),
    "accounts:dashboard_hod": (LOGIN, 403, 403, 200, 403),
    "accounts:dashboard_admin": ADMIN,
    "accounts:account": SIGNED_IN,
    "accounts:profile": SIGNED_IN,
    "accounts:password_change": SIGNED_IN,
    "accounts:sign_out_everywhere": POST_ONLY,
    "accounts:two_factor": SIGNED_IN,
    "accounts:two_factor_regenerate": POST_ONLY,
    "accounts:two_factor_device": POST_ONLY,
    "accounts:two_factor_device_confirm": (LOGIN, 302, 302, 302, 302),
    "accounts:registry_list": ADMIN,
    "accounts:registry_bulk": POST_ONLY,
    "accounts:registry_create": ADMIN,
    "accounts:registry_edit": ADMIN,
    "accounts:registry_hod": POST_ONLY,
    "accounts:user_list": ADMIN,
    "accounts:user_detail": ADMIN,
    "accounts:user_role": POST_ONLY,
    "accounts:user_reset_access": POST_ONLY,
    "academics:assign_teachers": ADMIN,
    "academics:import_index": ADMIN,
    "academics:import_upload": ADMIN,
    "academics:import_apply": POST_ONLY,
    "academics:import_template": ADMIN,
    "academics:results": ADMIN,
    "academics:grade_sheet": ADMIN,
    "academics:promotion": ADMIN,
    "academics:promotion_rule": ADMIN,
    "academics:promotion_confirm": (LOGIN, 403, 403, 403, 302),
    "academics:promotion_override": ADMIN,
    "academics:list": ADMIN,
    "academics:create": ADMIN,
    "academics:edit": ADMIN,
    "academics:delete": ADMIN,
    "enrollment:group": ADMIN,
    "enrollment:list": ADMIN,
    "enrollment:remove": ADMIN,
    "enrollment:missing": ADMIN,
    # The demo student's own pending course in the open round; nobody else may open it.
    "feedback:form": (LOGIN, 200, 403, 403, 403),
    "feedback:draft": POST_ONLY,
    "feedback:precheck": POST_ONLY,
    "feedback:done": (LOGIN, 302, 403, 403, 403),
    "feedback:questions": ADMIN,
    "feedback:question_create": ADMIN,
    "feedback:question_reorder": ADMIN,
    "feedback:question_edit": ADMIN,
    "feedback:question_duplicate": POST_ONLY,
    "feedback:question_toggle": POST_ONLY,
    "feedback:categories": ADMIN,
    "feedback:category_edit": ADMIN,
    "feedback:filter_terms": ADMIN,
    "feedback:filter_term_delete": POST_ONLY,
    "feedback:moderation": ADMIN,
    "feedback:moderation_decide": POST_ONLY,
    "feedback:windows": ADMIN,
    "feedback:window_create": ADMIN,
    "feedback:window_edit": ADMIN,
    "feedback:window_preview": ADMIN,
    # The demo teacher's own course in a closed round: the teacher, the CSE head and the Admin.
    "reports:overview": (LOGIN, 403, 200, 200, 403),
    "reports:course": (LOGIN, 403, 200, 200, 200),
    # Without HTMX the comment fragment sends the reader to its place on the report.
    "reports:comments": (LOGIN, 403, 302, 302, 302),
    "reports:report_comment": POST_ONLY,
    "reports:print": (LOGIN, 403, 200, 200, 200),
    "reports:note": POST_ONLY,
    "reports:analytics": ADMIN,
    "reports:hod_pending": (LOGIN, 403, 403, 200, 403),
    "reports:hod_remind": POST_ONLY,
    "reports:hod_audit": (LOGIN, 403, 403, 200, 403),
    "reports:export_course": (LOGIN, 403, 200, 200, 200),
    "reports:export_department": (LOGIN, 403, 403, 200, 200),
    "reports:export_pending": (LOGIN, 403, 403, 200, 200),
    "reports:export_university": ADMIN,
    "auditlog:log": ADMIN,
    "auditlog:export": ADMIN,
    "auditlog:verify": POST_ONLY,
    "notifications:badge": SIGNED_IN,
    "notifications:list": SIGNED_IN,
    "notifications:read_all": POST_ONLY,
    "notifications:open": POST_ONLY,
    "notifications:template_list": ADMIN,
    "notifications:template_edit": ADMIN,
    "notifications:template_test": POST_ONLY,
    "notifications:log": ADMIN,
    "core:home": PUBLIC,
    "core:server_time": PUBLIC,
    "core:healthz": PUBLIC,
    "core:settings": ADMIN,
    "core:dev_gallery": (404,) * 5,  # DEBUG only
    # The development-only Django admin (never installed in production).
    "admin:index": DJANGO_ADMIN,
    "admin:login": (200, 200, 200, 200, ANSWERS),
    "admin:logout": (ANSWERS,) * 5,
    "admin:password_change": DJANGO_ADMIN,
    "admin:password_change_done": DJANGO_ADMIN,
    "admin:autocomplete": DJANGO_ADMIN,
    "admin:jsi18n": DJANGO_ADMIN,
    "admin:auth_group_changelist": DJANGO_ADMIN,
    "admin:auth_group_add": DJANGO_ADMIN,
    "admin:axes_accessattempt_changelist": DJANGO_ADMIN,
    "admin:axes_accessattempt_add": DJANGO_ADMIN,
    "admin:axes_accesslog_changelist": DJANGO_ADMIN,
    "admin:axes_accesslog_add": DJANGO_ADMIN,
    "admin:axes_accessfailurelog_changelist": DJANGO_ADMIN,
    "admin:axes_accessfailurelog_add": DJANGO_ADMIN,
}
# Text that is English on a Bangla page on purpose: CSV column names are the file's headers,
# and the category list shows the English and the Bangla name side by side.
ENGLISH_ON_PURPOSE = {"academics:import_upload": {"section"}, "feedback:categories": {"*"}}


def _crawlable():
    """Every route but the Django admin's object pages, which take a raw object path."""
    return [route for route in all_routes() if "<path:object_id>" not in route.pattern]


def _english_allowed(route_name: str, text: str) -> bool:
    allowed = ENGLISH_ON_PURPOSE.get(route_name, set())
    return "*" in allowed or text in allowed


def _query(route_name: str) -> str:
    """An Admin names the department of a department-wide export."""
    if route_name in {"reports:export_department", "reports:export_pending"}:
        return f"?department={Department.objects.get(code=demo.CSE).pk}"
    return ""


@pytest.fixture
def sentinel(settings):
    templates = copy.deepcopy(settings.TEMPLATES)
    templates[0]["OPTIONS"]["string_if_invalid"] = INVALID + "[%s]"
    settings.TEMPLATES = templates


def test_every_route_has_an_expectation():
    assert {route.name for route in _crawlable()} == set(EXPECTED)


@pytest.mark.parametrize("language", ["en", "bn"])
@pytest.mark.parametrize("column", range(len(ROLES)), ids=ROLES)
def test_route_matrix(seeded, sentinel, column, language):
    role = ROLES[column]
    client = client_for(role, language)
    user = User.objects.filter(username=role).first()
    problems = []
    visited = 0
    for route in _crawlable():
        want = EXPECTED[route.name][column]
        for kwargs in sample_kwargs(route.name, user):
            url = reverse(route.name, kwargs=kwargs) + _query(route.name)
            response = client.get(url)
            visited += 1
            got = response.status_code
            if want == LOGIN:
                if got != 302 or not response["Location"].startswith(reverse("accounts:login")):
                    problems.append(f"{url}: {got}, expected the login redirect")
                continue
            if got >= 500 or (want != ANSWERS and got != want):
                problems.append(f"{url}: {got}, expected {want}")
                continue
            # Django's own admin pages are English-only and outside the design system.
            own_page = not route.name.startswith("admin:")
            if got != 200 or "text/html" not in response["Content-Type"] or not own_page:
                continue
            html = response.content.decode()
            problems += [f"{url}: shows {text[:120]!r}" for text in leaks(html)]
            if language == "bn":
                problems += [
                    f"{url}: English {text!r} on a Bangla page"
                    for text in untranslated(html)
                    if not _english_allowed(route.name, text)
                ]
    assert visited > len(EXPECTED)
    assert not problems, "\n".join(problems)
