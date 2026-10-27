"""Illustration system: small self-contained assets, motion off switches, CSP-clean pages."""

import re
from pathlib import Path

import pytest
from django.urls import reverse

ROOT = Path(__file__).resolve().parent.parent
ART_FILES = sorted(
    [
        *(ROOT / "templates/components/illustrations").glob("*.html"),
        *(ROOT / "static/art").glob("*.svg"),
    ]
)
FORBIDDEN_IN_ART = re.compile(
    r"<script|<style|\sstyle=\"|\son[a-z]+=\"|https?://(?!www\.w3\.org)|<image|data:image", re.I
)
ILLUSTRATION_ASSETS = [
    "scene_campus.html",
    "people.html",
    "bento_anon.html",
    "bento_combined.html",
    "bento_onevoice.html",
    "bento_closed.html",
    "bento_five.html",
    "bento_modes.html",
    "sec_password.html",
    "sec_encrypt.html",
    "sec_phone.html",
    "sec_unlink.html",
    "sec_nosite.html",
    "sec_screen.html",
]


@pytest.mark.parametrize("path", ART_FILES, ids=lambda p: p.name)
def test_art_file_is_small_and_self_contained(path):
    text = path.read_text(encoding="utf-8")

    assert path.stat().st_size < 60_000
    assert not FORBIDDEN_IN_ART.search(text)


def test_every_documented_asset_exists_and_is_listed_in_the_asset_guide():
    guide = (ROOT / "docs/ART_ASSETS.md").read_text(encoding="utf-8")
    for name in [*ILLUSTRATION_ASSETS, "alpona.svg", "rickshaw_border.svg"]:
        assert name in guide
        assert any(p.name == name for p in ART_FILES)


def test_motion_is_switched_off_by_reduced_motion_and_the_in_app_switch():
    css = (ROOT / "static/src/art.css").read_text(encoding="utf-8")
    landing = (ROOT / "static/src/landing_art.css").read_text(encoding="utf-8")

    assert "prefers-reduced-motion: reduce" in css
    assert ':root[data-motion="off"]' in css
    assert "prefers-reduced-motion: no-preference" in landing
    assert "animation-timeline: view()" in landing


def test_scene_figures_grow_on_small_screens_and_the_demo_cue_has_a_reduced_motion_twin():
    css = (ROOT / "static/src/art.css").read_text(encoding="utf-8")
    landing = (ROOT / "static/src/landing_art.css").read_text(encoding="utf-8")

    assert "@media (max-width: 480px)" in css and "--ws: 1.6" in css
    assert ".demo-plus" in landing and ".pv-bar-row.is-changed" in landing
    assert chr(0) not in landing


@pytest.mark.parametrize("language", ["bn", "en"])
def test_landing_carries_the_scene_demo_and_no_external_assets(client, language):
    client.cookies["django_language"] = language
    html = client.get(reverse("core:home")).content.decode()

    assert 'class="scene live enter"' in html
    assert 'src="/static/js/art.js"' in html and 'src="/static/js/demo.js"' in html
    assert "data-demo-send" in html and "data-demo-panel" in html
    assert 'aria-hidden="true"' in html.split("<svg", 2)[1][:400]
    assert not re.search(r"""(?:src|href)=["']https?://""", html)
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert "{#" not in html and "{%" not in html
