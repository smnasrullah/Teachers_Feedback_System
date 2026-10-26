"""Landing and sign-in pages: render in both languages, stay CSP-clean, load no external assets."""

import re
from pathlib import Path

import pytest
from django.urls import reverse

from tests.test_design_system import assert_csp_clean

ROOT = Path(__file__).resolve().parent.parent
EXTERNAL_ASSET = re.compile(r"""(?:src|href|action)=["']https?://""", re.IGNORECASE)
PAGES = [
    "core:home",
    "accounts:login",
    "accounts:signup",
    "accounts:password_forgot",
    "accounts:username_forgot",
]


@pytest.mark.parametrize("language", ["bn", "en"])
@pytest.mark.parametrize("name", PAGES)
def test_public_page_renders_clean(client, name, language):
    client.cookies["django_language"] = language
    response = client.get(reverse(name))
    html = response.content.decode()

    assert response.status_code == 200
    assert f'<html lang="{language}"' in html
    assert not EXTERNAL_ASSET.search(html)
    assert_csp_clean(html)


def test_landing_is_small_and_shows_the_headline_in_each_language(client):
    client.cookies["django_language"] = "bn"
    bangla = client.get(reverse("core:home")).content.decode()
    client.cookies["django_language"] = "en"
    english = client.get(reverse("core:home")).content.decode()

    assert "আপনার মতামত, নিরাপদে বেনামি।" in bangla
    assert "Honest feedback, kept anonymous." in english
    assert len(english.encode()) < 150_000


def test_landing_preview_is_an_accessible_tablist_with_sample_data(client):
    html = client.get(reverse("core:home")).content.decode()

    assert html.count('role="tab"') == 4
    assert html.count('role="tabpanel"') == 4
    assert 'x-data="dashPreview"' in html
    assert 'src="/static/js/preview.js"' in html
    assert html.index("js/preview.js") < html.index("alpine-csp.min.js")


def test_campus_illustration_is_small_and_decorative():
    svg = (ROOT / "templates/components/illustrations/campus_line.html").read_text(encoding="utf-8")

    assert len(svg.encode()) < 25_000
    assert 'aria-hidden="true"' in svg
    assert "style=" not in svg
