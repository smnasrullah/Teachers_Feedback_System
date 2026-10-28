import re
from pathlib import Path

import pytest
from django.core.paginator import Paginator
from django.test import RequestFactory
from django.urls import reverse

from apps.core import views
from apps.core.templatetags.ui import elided_pages, get_item, nav_links

ROOT = Path(__file__).resolve().parent.parent
INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)(?![^>]*application/json)", re.IGNORECASE)
INLINE_HANDLER = re.compile(r"\son[a-z]+=\"", re.IGNORECASE)
INLINE_STYLE = re.compile(r"\sstyle=\"", re.IGNORECASE)


def assert_csp_clean(html):
    assert not INLINE_SCRIPT.search(html), "inline <script> found"
    assert not INLINE_HANDLER.search(html), "inline event handler found"
    assert not INLINE_STYLE.search(html), "inline style attribute found"


@pytest.fixture
def gallery(client, settings):
    settings.DEBUG = True
    return client.get(reverse("core:dev_gallery"))


def test_landing_page_has_sections_skip_link_and_external_theme_script(client):
    response = client.get(reverse("core:home"))
    html = response.content.decode()

    assert response.status_code == 200
    assert 'href="#main"' in html
    assert 'src="/static/js/theme.js"' in html
    for anchor in ("how-title", "promise-title", "roles-title", "faq-title"):
        assert f'id="{anchor}"' in html
    assert_csp_clean(html)


def test_theme_script_loads_before_stylesheet(client):
    html = client.get(reverse("core:home")).content.decode()

    assert html.index("js/theme.js") < html.index("css/tailwind.css")


def test_gallery_is_hidden_unless_debug(client, settings):
    settings.DEBUG = False

    assert client.get(reverse("core:dev_gallery")).status_code == 404


def test_gallery_renders_every_component_without_inline_code(gallery):
    html = gallery.content.decode()

    assert gallery.status_code == 200
    for marker in (
        'class="nav',
        'class="sidebar"',
        'class="bottomnav"',
        'class="card stat-tile"',
        "badge badge-pending",
        'class="btn btn-primary"',
        'class="input"',
        'class="select"',
        'class="textarea"',
        '<dialog class="modal"',
        "toast toast-error",
        'class="breadcrumb"',
        'class="empty"',
        'class="skeleton',
        'class="progress-ring"',
        'role="radiogroup"',
        'class="data-table"',
        'class="pagination"',
        "data-chart=",
        "stub-sealed",
    ):
        assert marker in html, marker
    assert_csp_clean(html)


def test_star_rating_shows_numeric_value_and_checked_state(gallery):
    html = gallery.content.decode()

    assert "4 / 5" in html
    assert re.search(r'value="4"\s+checked', html)
    assert 'aria-invalid="true"' in html


def test_form_error_is_linked_to_its_field(gallery):
    html = gallery.content.decode()

    assert 'aria-describedby="g-email-error"' in html
    assert 'id="g-email-error" role="alert"' in html


def test_unknown_url_renders_branded_404(client):
    response = client.get("/no-such-page")

    assert response.status_code == 404
    assert "404" in response.content.decode()
    assert 'href="#main"' in response.content.decode()


def test_403_and_500_pages_render():
    request = RequestFactory().get("/")
    request.user = type("Anon", (), {"get_username": lambda self: ""})()
    forbidden = views.error_403(request)
    broken = views.error_500(request)

    assert forbidden.status_code == 403
    assert b"403" in forbidden.content
    assert broken.status_code == 500
    assert b"500" in broken.content


def test_language_switch_sets_language(client):
    response = client.post(reverse("set_language"), {"language": "en", "next": "/"})
    page = client.get(reverse("core:home"))

    assert response.status_code == 302
    assert '<html lang="en">' in page.content.decode()


def test_default_language_is_bangla(client):
    html = client.get(reverse("core:home")).content.decode()

    assert '<html lang="bn">' in html
    assert "শিক্ষক" in html


def test_elided_pages_marks_gaps_with_none():
    page = Paginator(range(1, 201), 10).page(10)

    assert elided_pages(page) == [1, None, 9, 10, 11, None, 20]


def test_nav_links_drops_group_headings():
    items = [{"group": "A"}, {"label": "x", "url": "/"}]

    assert nav_links(items) == [{"label": "x", "url": "/"}]


def test_get_item_returns_blank_for_missing_key():
    assert get_item({"a": 1}, "a") == 1
    assert get_item({"a": 1}, "b") == ""


def test_component_css_uses_tokens_only():
    css = (ROOT / "static/src/components.css").read_text(encoding="utf-8")

    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css)
    assert not re.search(r"\brgba?\(", css)


@pytest.mark.parametrize("name", ["art.css", "landing.css", "landing_art.css"])
def test_page_css_sets_colours_only_through_custom_properties(name):
    """Literal colours belong in a palette variable, never in a rule or a var() fallback.

    A mask image is the one exception: only its alpha channel matters, so its colour is not themed.
    """
    for line in (ROOT / "static/src" / name).read_text(encoding="utf-8").splitlines():
        declaration = line.strip()
        if declaration.startswith("--") or "mask-image:" in declaration:
            continue
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(", declaration), declaration


def test_tokens_cover_blueprint_light_and_dark_values():
    css = (ROOT / "static/src/tokens.css").read_text(encoding="utf-8")

    assert "@custom-variant dark (&:where(.dark, .dark *));" in css
    assert "@theme inline" in css
    for value in ("#f8fafc", "#1e3a8a", "#0f172a", "#93b4ff", "#7c8da5", "#fbbf24"):
        assert value in css


def _token_sets() -> dict[str, dict[str, str]]:
    """The hex tokens of the light (:root) and dark (.dark) blocks of tokens.css."""
    css = (ROOT / "static/src/tokens.css").read_text(encoding="utf-8")
    sets = {}
    for theme, selector in (("light", r":root\s*\{"), ("dark", r"\.dark\s*\{")):
        block = css[re.search(selector, css).end() :].split("}", 1)[0]
        sets[theme] = dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", block))
    sets["dark"] = {**sets["light"], **sets["dark"]}
    return sets


def _luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first: str, second: str) -> float:
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_every_badge_meets_aa_contrast(theme):
    css = (ROOT / "static/src/components.css").read_text(encoding="utf-8")
    tokens = _token_sets()[theme]
    badges = re.findall(
        r"\.(badge-[a-z]+) \{\s*background: var\(--([a-z-]+)\);\s*color: var\(--([a-z-]+)\);", css
    )
    assert len(badges) >= 5
    for name, background, text in badges:
        ratio = _contrast(tokens[background], tokens[text])
        assert ratio >= 4.5, f"{name} in {theme}: {ratio:.2f}"


def test_fonts_and_license_are_vendored():
    fonts = ROOT / "static/fonts"

    assert (fonts / "LICENSE-OFL.txt").exists()
    assert len(list(fonts.glob("*.woff2"))) == 8


def test_buttons_are_not_full_width_by_default(gallery):
    assert 'class="btn btn-primary"' in gallery.content.decode()
    assert "btn-block" not in gallery.content.decode()
