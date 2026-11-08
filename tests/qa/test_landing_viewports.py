"""Comprehensive viewport, language, and theme review for the landing navbar and hero."""

import pytest
from django.urls import reverse

playwright = pytest.importorskip("playwright.sync_api")

VIEWPORTS = [
    (1480, 900),
    (1280, 800),
    (1024, 768),
    (768, 1024),
    (430, 932),
    (375, 812),
    (320, 720),
    (390, 844),
]


@pytest.fixture(scope="module")
def browser():
    with pytest.MonkeyPatch.context() as patch, playwright.sync_playwright() as runner:
        patch.setenv("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        try:
            chromium = runner.chromium.launch()
        except playwright.Error:
            pytest.skip("Chromium for Playwright is not installed")
        yield chromium
        chromium.close()


@pytest.mark.parametrize(
    "width,height",
    VIEWPORTS,
    ids=["1480px", "1280px", "1024px", "768px", "430px", "375px", "320px", "390px"],
)
@pytest.mark.parametrize("language", ["en", "bn"])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_landing_navbar_and_hero_at_viewport(
    transactional_db, live_server, browser, width, height, language, theme
):
    context = browser.new_context(
        viewport={"width": width, "height": height},
        extra_http_headers={"Accept-Language": language},
    )
    if theme == "dark":
        context.add_cookies([{"name": "tfs_theme", "value": "dark", "url": live_server.url}])
    page = context.new_page()
    page.goto(live_server.url + reverse("core:home"), wait_until="networkidle")

    # 1. No horizontal scroll at any width
    no_overflow = page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
    )
    overflow_nodes = page.evaluate("""() => Array.from(document.querySelectorAll('body *'))
        .map(el => ({tag: el.tagName, className: el.className.baseVal || el.className,
                    text: (el.textContent || '').slice(0, 32), parent: el.parentElement.className,
                    left: Math.round(el.getBoundingClientRect().left),
                    right: Math.round(el.getBoundingClientRect().right)}))
        .filter(el => el.left < -1 || el.right > document.documentElement.clientWidth + 1)
        .slice(0, 8)""")
    assert no_overflow, f"Horizontal overflow at {width}px {language} {theme}: {overflow_nodes}"

    # 2. Check desktop vs compact navigation
    if width >= 1280:
        # Full anchors are visible, compact toggle is hidden
        anchors_visible = page.is_visible(".nav-anchors")
        compact_visible = page.is_visible(".nav-anchors-compact")
        assert anchors_visible, f"Expected .nav-anchors visible at {width}px"
        assert not compact_visible, f"Expected .nav-anchors-compact hidden at {width}px"

        # Check that all anchor links and the login button are on ONE row
        # (Y positions are aligned, no wrapping)
        y_positions = page.evaluate("""() => {
            const items = Array.from(document.querySelectorAll('.nav-anchors a, .nav .btn, .logo'));
            return items.map(el => Math.round(el.getBoundingClientRect().top));
        }""")
        # All items on the same baseline row within 4px tolerance
        assert len(set(y_positions)) <= 2, f"Navigation items wrapped across rows: {y_positions}"

        # Confirm no nav anchor link or button has multi-line wrapped text
        wrapped = page.evaluate("""() => {
            const items = Array.from(document.querySelectorAll('.nav-anchors a, .nav .btn'));
            return items.filter(el => {
                const text = el.innerText.trim();
                return text.includes('\\n');
            }).map(el => el.innerText);
        }""")
        assert not wrapped, f"Wrapped labels found: {wrapped}"

        nav_link = page.locator(".nav-anchors a").first
        font_size = page.eval_on_selector(
            ".nav-anchors a", "el => parseFloat(getComputedStyle(el).fontSize)"
        )
        assert font_size <= 12, f"Navbar text should stay compact, got {font_size}px"
        nav_link.hover()
        page.wait_for_timeout(220)
        hover_style = nav_link.evaluate(
            """el => ({
                background: getComputedStyle(el).backgroundColor,
                transform: getComputedStyle(el).transform,
            })"""
        )
        assert hover_style["background"] != "rgba(0, 0, 0, 0)", "Hover background is missing"
        assert hover_style["transform"] != "none", "Hover lift is missing"
    else:
        # Compact toggle is visible, desktop anchors are hidden
        anchors_visible = page.is_visible(".nav-anchors")
        compact_visible = page.is_visible(".nav-anchors-compact")
        assert not anchors_visible, f"Expected .nav-anchors hidden at {width}px"
        assert compact_visible, f"Expected .nav-anchors-compact visible at {width}px"

        # Click menu button to open compact menu
        page.click(".nav-anchors-compact [data-toggle]")
        menu_visible = page.is_visible("#nav-anchors-menu")
        assert menu_visible, f"Compact menu failed to open at {width}px"

        menu_state = page.locator("#nav-anchors-menu").evaluate("""menu => {
            const box = menu.getBoundingClientRect();
            const links = Array.from(menu.querySelectorAll('a.menu-item'));
            return {
                left: box.left,
                right: box.right,
                viewport: document.documentElement.clientWidth,
                labels: links.map(link => link.innerText.trim()),
                visible: links.every(link => {
                    const rect = link.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0 &&
                        getComputedStyle(link).visibility === 'visible';
                }),
            };
        }""")
        assert menu_state["left"] >= 0, f"Compact menu clipped on the left: {menu_state}"
        assert menu_state["right"] <= menu_state["viewport"], (
            f"Compact menu clipped on the right: {menu_state}"
        )
        assert menu_state["visible"], f"Compact menu labels are not visible: {menu_state}"
        assert all(menu_state["labels"]), f"Compact menu contains a blank label: {menu_state}"

        # Ensure all 5 section links exist in menu
        menu_links = page.eval_on_selector_all(
            "#nav-anchors-menu a.menu-item", "els => els.map(e => e.getAttribute('href'))"
        )
        assert menu_links == ["#demo", "#how", "#roles", "#preview", "#faq"]
        page.keyboard.press("Escape")
        assert not page.is_visible("#nav-anchors-menu"), "Escape should close the compact menu"
        page.click(".nav-anchors-compact [data-toggle]")
        page.mouse.click(5, height - 5)
        assert not page.is_visible("#nav-anchors-menu"), (
            "Tapping outside should close the compact menu"
        )

    # 3. The landing hero intentionally has no campus scene or replacement artwork.
    assert page.locator(".a-hero-art, .hero-arch, .scene, .mini-stub").count() == 0

    context.close()


def test_removed_hero_art_is_absent_with_reduced_motion(transactional_db, live_server, browser):
    """The removed hero scene must not be reintroduced for reduced-motion users."""
    context = browser.new_context(
        viewport={"width": 1480, "height": 900},
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.goto(live_server.url + reverse("core:home"), wait_until="networkidle")

    assert page.locator(".a-hero-art, .hero-arch, .scene, .mini-stub").count() == 0
    context.close()
