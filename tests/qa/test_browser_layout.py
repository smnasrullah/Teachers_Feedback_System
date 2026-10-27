"""A real browser at phone width: no page of any role scrolls sideways (BLUEPRINT: mobile-first
360px). Skips when Chromium for Playwright or the built stylesheet is missing."""

from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from tests.factories import claim, make_admin, make_hod, make_student, make_teacher, sign_in

playwright = pytest.importorskip("playwright.sync_api")
STYLESHEET = Path(settings.BASE_DIR) / "static/css/tailwind.css"
PHONE = {"width": 360, "height": 780}
WIDE = "document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"


@pytest.fixture(scope="module")
def browser():
    if not STYLESHEET.exists():
        pytest.skip("the stylesheet is not built (python manage.py tailwind build)")
    # Playwright's sync API runs an event loop on this thread; the test's own ORM calls are
    # still plain synchronous code (Django's documented escape hatch for this case).
    with pytest.MonkeyPatch.context() as patch, playwright.sync_playwright() as runner:
        patch.setenv("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        try:
            chromium = runner.chromium.launch()
        except playwright.Error:
            pytest.skip("Chromium for Playwright is not installed (playwright install chromium)")
        yield chromium
        chromium.close()


def _session_cookie(user, server_url):
    client = Client()
    sign_in(client, user)
    return {
        "name": settings.SESSION_COOKIE_NAME,
        "value": client.cookies[settings.SESSION_COOKIE_NAME].value,
        "url": server_url,
    }


def _users():
    return {
        "student": claim(make_student()),
        "teacher": claim(make_teacher()),
        "hod": make_hod(),
        "admin": make_admin(),
    }


PAGES = {
    "student": ["accounts:dashboard_student", "accounts:account", "accounts:profile"],
    "teacher": ["accounts:dashboard_teacher", "reports:overview", "accounts:account"],
    "hod": ["accounts:dashboard_hod", "reports:hod_pending", "accounts:account"],
    "admin": ["accounts:dashboard_admin", "accounts:user_list", "feedback:questions"],
}


@pytest.mark.parametrize("language", ["bn", "en"])
def test_no_page_scrolls_sideways_on_a_phone(transactional_db, live_server, browser, language):
    users = _users()
    wide = []
    for role, names in [("anonymous", ["core:home", "accounts:login"]), *PAGES.items()]:
        context = browser.new_context(
            viewport=PHONE, extra_http_headers={"Accept-Language": language}
        )
        if role != "anonymous":
            context.add_cookies([_session_cookie(users[role], live_server.url)])
        page = context.new_page()
        for name in names:
            page.goto(live_server.url + reverse(name), wait_until="networkidle")
            if page.evaluate(WIDE):
                wide.append(f"{role} {reverse(name)}")
        context.close()
    assert not wide, wide


SHIFTS = """
window.__cls = 0;
new PerformanceObserver((list) => {
  for (const entry of list.getEntries()) if (!entry.hadRecentInput) window.__cls += entry.value;
}).observe({type: 'layout-shift', buffered: true});
"""
CLS_LIMIT = 0.1  # "good" Cumulative Layout Shift
DESKTOP = {"width": 1440, "height": 900}


@pytest.mark.parametrize("viewport", [PHONE, DESKTOP], ids=["phone", "desktop"])
def test_pages_do_not_jump_while_they_load(transactional_db, live_server, browser, viewport):
    """A first visit (nothing cached): fonts and the live clock arrive without moving the page."""
    users = _users()
    jumps = []
    for role, names in [("anonymous", ["core:home", "accounts:login"]), *PAGES.items()]:
        for name in names:
            context = browser.new_context(
                viewport=viewport, extra_http_headers={"Accept-Language": "bn"}
            )
            context.add_init_script(SHIFTS)
            if role != "anonymous":
                context.add_cookies([_session_cookie(users[role], live_server.url)])
            page = context.new_page()
            page.goto(live_server.url + reverse(name), wait_until="networkidle")
            page.wait_for_timeout(300)
            shift = page.evaluate("window.__cls")
            if shift > CLS_LIMIT:
                jumps.append(f"{role} {reverse(name)}: {shift:.2f}")
            context.close()
    assert not jumps, jumps
