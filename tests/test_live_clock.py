"""The live clock and countdowns (P26): page server time, CSP, time endpoint, JS logic."""

import json
import re
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from django.template import Context, Template
from django.urls import reverse
from django.utils import timezone, translation

from apps.core.services.clock import utc_iso
from apps.feedback.models import FeedbackWindow
from tests.test_academics import make_semester
from tests.test_design_system import assert_csp_clean
from tests.test_feedback_core import make_window

ROOT = Path(__file__).resolve().parent.parent
ISO_UTC = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")


def render(source, **context):
    return Template("{% load ui rounds %}" + source).render(Context(context))


def test_page_exposes_the_server_time_in_utc_once_and_loads_the_clock_scripts(client):
    before = datetime.now(UTC) - timedelta(seconds=1)
    html = client.get(reverse("core:home")).content.decode()
    after = datetime.now(UTC) + timedelta(seconds=1)

    values = re.findall(r'data-server-now="([^"]*)"', html)
    assert len(values) == 1 and ISO_UTC.match(values[0])
    assert before <= datetime.fromisoformat(values[0].replace("Z", "+00:00")) <= after
    assert "data-clock" in html
    for script in ("clock_core.js", "clock.js"):
        assert re.search(rf'<script src="/static/js/{script}" nonce="[^"]+"', html)
    assert_csp_clean(html)


def test_time_endpoint_is_public_uncached_and_only_tells_the_time(client):
    response = client.get(reverse("core:server_time"))

    assert response.status_code == 200
    assert "no-cache" in response["Cache-Control"] or "max-age=0" in response["Cache-Control"]
    body = json.loads(response.content)
    assert list(body) == ["now"] and ISO_UTC.match(body["now"])
    assert client.post(reverse("core:server_time")).status_code == 405


def test_countdown_renders_the_target_in_utc_with_label_and_done_text():
    dhaka_noon = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.get_fixed_timezone(360))
    html = render('{% countdown moment "Closes in" "Closed" %}', moment=dhaka_noon)

    assert 'data-countdown-to="2026-11-01T06:00:00.000Z"' in html
    assert 'data-countdown-label="Closes in"' in html
    assert 'data-countdown-done="Closed"' in html
    assert 'data-countdown-text aria-hidden="true"' in html
    assert 'class="sr-only" data-countdown-sr-text' in html
    assert_csp_clean(html)


@pytest.mark.django_db
def test_window_countdown_follows_the_round_state():
    semester = make_semester(current=True)
    open_round = make_window(semester)
    upcoming = make_window(semester, opens=timedelta(days=1), closes=timedelta(days=5))
    closed = make_window(semester, opens=timedelta(days=-5), closes=timedelta(days=-1))
    inactive = make_window(semester, is_active=False)

    def shown(window):
        with translation.override("en"):
            return render("{% window_countdown window %}", window=window)

    assert f'data-countdown-to="{utc_iso(open_round.closes_at)}"' in shown(open_round)
    assert 'data-countdown-label="Opens in"' in shown(upcoming)
    assert shown(closed).strip() == ""
    assert shown(inactive).strip() == ""
    assert shown(None).strip() == ""
    assert FeedbackWindow.objects.count() == 4


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_clock_logic_passes_its_node_tests():
    result = subprocess.run(  # noqa: S603
        [shutil.which("node"), "--test", str(ROOT / "tests" / "js" / "clock_core.test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-2000:]
