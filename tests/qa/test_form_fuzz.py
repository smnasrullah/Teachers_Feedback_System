"""Every POST endpoint, as the role allowed to use it, with hostile input: no server error, no
reflected markup, errors in the reader's language; and no POST anywhere without a CSRF token."""

from html.parser import HTMLParser

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.core.services.demo import constants as demo
from tests.qa.conftest import ROLES, client_for, sample_kwargs
from tests.qa.pages import untranslated
from tests.qa.test_route_crawl import ANSWERS, EXPECTED, _crawlable, _english_allowed

SCRIPT = "<script>alert(1)</script>"
MALICIOUS = f'{SCRIPT}\' OR 1=1; DROP TABLE users; -- =HYPERLINK("x")'
WRONG = {"number": "abc", "date": "31-31-2026", "email": "not-an-email", "time": "25:99"}
# Who may use a POST-only endpoint (the rest take the first role that may open the page).
OWNERS = {
    "accounts:login_second_factor": "anonymous",
    "accounts:login_two_factor_setup": "anonymous",
    "accounts:password_forgot_new": "anonymous",
    "accounts:two_factor_device_confirm": demo.STUDENT,
    "academics:promotion_confirm": demo.ADMIN,
    "reports:comments": demo.TEACHER,
    "feedback:done": demo.STUDENT,
    "set_language": demo.STUDENT,
    "accounts:logout": demo.STUDENT,
    "accounts:sign_out_everywhere": demo.STUDENT,
    "accounts:two_factor_regenerate": demo.STUDENT,
    "accounts:two_factor_device": demo.STUDENT,
    "feedback:draft": demo.STUDENT,
    "feedback:precheck": demo.STUDENT,
    "notifications:read_all": demo.STUDENT,
    "notifications:open": demo.STUDENT,
    "reports:report_comment": demo.TEACHER,
    "reports:note": demo.TEACHER,
    "reports:hod_remind": demo.HOD,
}


class _Fields(HTMLParser):
    """Names and kinds of the fields of the page's POST forms."""

    def __init__(self):
        super().__init__()
        self.in_post_form = False
        self.fields: dict[str, str] = {}
        self.options: dict[str, list[str]] = {}
        self._select = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.in_post_form = (attrs.get("method") or "").lower() == "post"
        elif self.in_post_form and tag in {"input", "textarea", "select"}:
            name = attrs.get("name")
            if name and name != "csrfmiddlewaretoken":
                kind = attrs.get("type", "text") if tag == "input" else tag
                self.fields[name] = kind
                self._select = name if tag == "select" else None
        elif tag == "option" and self._select and attrs.get("value"):
            self.options.setdefault(self._select, []).append(attrs["value"])

    def handle_endtag(self, tag):
        if tag == "form":
            self.in_post_form = False
        elif tag == "select":
            self._select = None


def _fields(html: str) -> dict[str, str]:
    parser = _Fields()
    parser.feed(html)
    return {name: kind for name, kind in parser.fields.items() if kind not in {"submit", "hidden"}}


def _payloads(fields: dict[str, str]) -> dict[str, dict]:
    text_fields = fields or {"text": "text", "value": "text"}
    return {
        "empty": {},
        "oversized": dict.fromkeys(text_fields, "A" * 20000),
        "malicious": dict.fromkeys(text_fields, MALICIOUS),
        "wrong-type": {
            name: WRONG.get(kind, "99999999" if kind == "select" else "\x00")
            for name, kind in text_fields.items()
        },
    }


def _owner(route_name: str) -> str | None:
    if route_name in OWNERS:
        return OWNERS[route_name]
    expected = EXPECTED[route_name]
    if expected[0] == 200:
        return "anonymous"
    for role, want in zip(ROLES[1:], expected[1:], strict=True):
        if want in {200, ANSWERS}:
            return role
    return demo.ADMIN if expected[-1] == 405 else None


def _stored_markup(client, response) -> bool:
    """After an accepted POST, does the page it leads to show the script tag unescaped?"""
    if response.status_code != 302 or not response["Location"].startswith("/"):
        return False
    landing = client.get(response["Location"])
    return "text/html" in landing.get("Content-Type", "") and SCRIPT in landing.content.decode()


POST_ROUTES = [route for route in _crawlable() if not route.name.startswith("admin:")]


@pytest.mark.parametrize("route", POST_ROUTES, ids=[route.name for route in POST_ROUTES])
def test_hostile_input_never_breaks_a_form(seeded, route):
    role = _owner(route.name)
    if role is None:
        pytest.skip("no role may use this route")
    user = User.objects.filter(username=role).first()
    problems = []
    for kwargs in sample_kwargs(route.name, user)[:2]:
        url = reverse(route.name, kwargs=kwargs)
        page = client_for(role, "bn").get(url)
        html_page = page.status_code == 200 and "text/html" in page.get("Content-Type", "")
        fields = _fields(page.content.decode()) if html_page else {}
        for variant, data in _payloads(fields).items():
            client = client_for(role, "bn")
            response = client.post(url, data)
            status = response.status_code
            if status >= 500:
                problems.append(f"{variant} {url}: {status}")
                continue
            if _stored_markup(client, response):
                problems.append(f"{variant} {url}: the stored script tag is shown unescaped")
            if response.streaming or "text/html" not in response.get("Content-Type", ""):
                continue
            body = response.content.decode()
            if SCRIPT in body:
                problems.append(f"{variant} {url}: the script tag came back unescaped")
            if status in {200, 400}:
                problems += [
                    f"{variant} {url}: English {text!r} in a Bangla answer"
                    for text in untranslated(body)
                    if not _english_allowed(route.name, text)
                ]
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("role", ROLES)
def test_no_post_is_accepted_without_a_csrf_token(seeded, role):
    user = User.objects.filter(username=role).first()
    accepted = []
    for route in _crawlable():
        for kwargs in sample_kwargs(route.name, user)[:1]:
            url = reverse(route.name, kwargs=kwargs)
            response = client_for(role, enforce_csrf_checks=True).post(url, {"x": "1"})
            if response.status_code != 403:
                accepted.append(f"{url}: {response.status_code}")
    assert not accepted, "\n".join(accepted)
