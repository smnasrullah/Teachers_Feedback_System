"""Browser QA walk: every role and nav link, phone and desktop, light and dark, Bangla and English.

Run it against a dev server seeded with ``seed_demo`` (never against real data):

    python manage.py seed_demo --password <pw>
    python manage.py runserver 127.0.0.1:8765
    python scripts/qa_walk.py --base http://127.0.0.1:8765 --password <pw> --out <dir>
        [--axe path/to/axe.min.js]

It writes ``report.json`` and screenshots to ``--out`` and exits 1 when it found a problem:
console errors, CSP violations, failed or 4xx/5xx requests, horizontal scroll, focus that is not
visible, a keyboard trap, layout shift above 0.1, a live clock that does not tick or a countdown
that does not reload at zero, and (with ``--axe``) axe-core violations.
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

ROLES = ("anonymous", "demo_student", "demo_teacher", "demo_hod", "demo_admin")
WIDTHS = {"phone": (360, 780), "desktop": (1440, 900)}
SKIPPED_PATHS = ("/logout/", "/i18n/", "/admin/", "/static/", "/media/")
DOWNLOADS = (".csv", ".xlsx", ".pdf")
TAB_PRESSES = 30
CLS_LIMIT = 0.1
AXE_IMPACTS = {"serious", "critical"}
CLOCK_STEP, MAX_JUMP, RELOAD_WAIT = 1_000, 1_000_000_000, 10_000  # milliseconds

# Runs before any page script; CDP init scripts are not subject to the page's CSP.
WATCH = """
window.__qa = {csp: [], cls: 0};
document.addEventListener('securitypolicyviolation', (e) => {
  window.__qa.csp.push(e.violatedDirective + ' ' + (e.blockedURI || 'inline'));
});
new PerformanceObserver((list) => {
  for (const entry of list.getEntries()) {
    if (!entry.hadRecentInput) window.__qa.cls += entry.value;
  }
}).observe({type: 'layout-shift', buffered: true});
"""

OVERFLOW = """() => {
  const width = document.documentElement.clientWidth;
  const wide = document.documentElement.scrollWidth > width + 1;
  const culprits = [];
  if (wide) {
    for (const el of document.body.querySelectorAll('*')) {
      const box = el.getBoundingClientRect();
      if (box.width && box.right > width + 1 && getComputedStyle(el).position !== 'fixed') {
        culprits.push(el.tagName.toLowerCase() + (el.className && typeof el.className === 'string'
          ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.') : ''));
        if (culprits.length >= 3) break;
      }
    }
  }
  return culprits;
}"""

FOCUS_STATE = """() => {
  const el = document.activeElement;
  if (!el || el === document.body) return null;
  window.__qaIds = window.__qaIds || new WeakMap();
  if (!window.__qaIds.has(el)) window.__qaIds.set(el, Math.random());
  const style = getComputedStyle(el);
  const visible = (style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0)
    || (style.boxShadow && style.boxShadow !== 'none');
  const box = el.getBoundingClientRect();
  return {
    id: String(window.__qaIds.get(el)),
    key: el.tagName + '#' + el.id + '.' + el.className + '@' + (el.getAttribute('href') || ''),
    visible: visible,
    shown: box.width > 0 && box.height > 0,
  };
}"""


@dataclass
class PageResult:
    role: str
    combo: str
    url: str
    status: int | None = None
    problems: list[str] = field(default_factory=list)


@dataclass
class Walk:
    base: str
    password: str
    out: Path
    axe: str | None
    results: list[PageResult] = field(default_factory=list)
    checked_links: dict[str, int] = field(default_factory=dict)

    def same_origin(self, url: str) -> bool:
        return urlparse(url).netloc == urlparse(self.base).netloc


def _login(page, walk: Walk, role: str, language: str | None = None) -> None:
    """Sign in; the account's saved language wins at login, so switch it the way a person does."""
    page.goto(urljoin(walk.base, "/login/"))
    page.fill("#id_username", role)
    page.fill("#id_password", walk.password)
    with page.expect_navigation():
        page.click("form button.btn-primary[type=submit]")
    if language and page.get_attribute("html", "lang") != language:
        with page.expect_navigation():
            page.click(f"button[name=language][value={language}]")


def _nav_links(page, walk: Walk) -> list[str]:
    hrefs = page.eval_on_selector_all(
        "nav a[href], header a[href], .bottom-nav a[href]", "els => els.map(e => e.href)"
    )
    links = []
    for href in hrefs:
        path = urlparse(href).path
        if (
            walk.same_origin(href)
            and not path.startswith(SKIPPED_PATHS)
            and not path.endswith(DOWNLOADS)
            and href.split("#")[0] not in links
        ):
            links.append(href.split("#")[0])
    return links


def _keyboard(page) -> list[str]:
    problems, stuck, last = [], 0, None
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    for _ in range(TAB_PRESSES):
        page.keyboard.press("Tab")
        state = page.evaluate(FOCUS_STATE)
        if state is None:
            continue
        if state["shown"] and not state["visible"]:
            problems.append(f"focus not visible on {state['key'][:90]}")
        stuck = stuck + 1 if state["id"] == last else 0
        if stuck >= 3:
            problems.append(f"keyboard trap at {state['key'][:90]}")
            break
        last = state["id"]
    return sorted(set(problems))


def _axe(page, walk: Walk) -> list[str]:
    if not walk.axe:
        return []
    page.evaluate(Path(walk.axe).read_text(encoding="utf-8"))
    found = page.evaluate(
        "async () => (await axe.run(document, {resultTypes: ['violations']})).violations"
        ".map(v => ({id: v.id, impact: v.impact, nodes: v.nodes.slice(0, 2)"
        ".map(n => n.target.join(' '))}))"
    )
    return [
        f"axe {item['id']} ({item['impact']}): {', '.join(item['nodes'])}"
        for item in found
        if item["impact"] in AXE_IMPACTS
    ]


def _check_links(context, page, walk: Walk) -> list[str]:
    problems = []
    hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
    for href in {h.split("#")[0] for h in hrefs}:
        path = urlparse(href).path
        if not walk.same_origin(href) or path.startswith(("/logout/", "/i18n/")):
            continue
        key = f"{id(context)}:{href}"
        if key not in walk.checked_links:
            response = context.request.get(href, max_redirects=0)
            walk.checked_links[key] = response.status
        if walk.checked_links[key] >= 400 and walk.checked_links[key] not in {403}:
            problems.append(f"broken link {path} -> {walk.checked_links[key]}")
    return problems


def _visit(page, context, walk: Walk, role: str, combo: str, url: str, shot: str | None):
    result = PageResult(role, combo, urlparse(url).path)
    console, failed = [], []
    page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: console.append(f"pageerror: {e}"))
    page.on(
        "response",
        lambda r: (
            failed.append(f"{r.status} {urlparse(r.url).path}")
            if r.status >= 400 and walk.same_origin(r.url)
            else None
        ),
    )
    page.on("requestfailed", lambda r: failed.append(f"failed {urlparse(r.url).path}"))
    try:
        response = page.goto(url, wait_until="networkidle")
    except PlaywrightError as error:
        result.problems.append(f"navigation error: {error.message[:120]}")
        walk.results.append(result)
        return
    result.status = response.status if response else None
    page.wait_for_timeout(300)
    qa = page.evaluate("() => window.__qa")
    result.problems += [f"console: {text[:200]}" for text in console]
    result.problems += [f"csp: {text}" for text in qa["csp"]]
    result.problems += [f"request: {text}" for text in failed if not text.startswith("403 ")]
    if result.status and result.status >= 400 and result.status != 403:
        result.problems.append(f"status {result.status}")
    if qa["cls"] > CLS_LIMIT:
        result.problems.append(f"layout shift {qa['cls']:.2f}")
    culprits = page.evaluate(OVERFLOW)
    if culprits:
        result.problems.append(f"horizontal scroll: {', '.join(culprits)}")
    result.problems += _keyboard(page)
    result.problems += _axe(page, walk)
    result.problems += _check_links(context, page, walk)
    if shot:
        page.screenshot(path=str(walk.out / shot), full_page=True)
    walk.results.append(result)


def _combo_pages(browser, walk: Walk, role: str, width: str, theme: str, language: str):
    combo = f"{width}-{theme}-{language}"
    viewport = dict(zip(("width", "height"), WIDTHS[width], strict=True))
    context = browser.new_context(
        viewport=viewport,
        color_scheme=theme,
        locale="bn-BD" if language == "bn" else "en-US",
        extra_http_headers={"Accept-Language": language},
    )
    host = urlparse(walk.base).hostname
    context.add_cookies(
        [
            {"name": "django_language", "value": language, "domain": host, "path": "/"},
            {"name": "tfs_theme", "value": theme, "domain": host, "path": "/"},
        ]
    )
    context.add_init_script(WATCH)
    page = context.new_page()
    if role != "anonymous":
        _login(page, walk, role, language)
    start = page.url if role != "anonymous" else urljoin(walk.base, "/")
    pages = [start, *[link for link in _nav_links(page, walk) if link != start]]
    if role == "anonymous":
        page.goto(start)
        pages = [
            start,
            *_nav_links(page, walk),
            urljoin(walk.base, "/login/"),
            urljoin(walk.base, "/signup/"),
            urljoin(walk.base, "/password/forgot/"),
        ]
    for index, url in enumerate(dict.fromkeys(pages)):
        fresh = context.new_page()
        shot = f"{role}-{combo}-{index:02d}.png"
        _visit(fresh, context, walk, role, combo, url, shot)
        fresh.close()
    context.close()


def _clock_checks(browser, walk: Walk) -> list[str]:
    """The live clock ticks with seconds; a running countdown reloads the page at zero."""
    problems = []
    context = browser.new_context(extra_http_headers={"Accept-Language": "en"})
    page = context.new_page()
    _login(page, walk, "demo_student")
    first = page.text_content("[data-clock-time]") or ""
    page.wait_for_timeout(1500)
    second = page.text_content("[data-clock-time]") or ""
    if first == second or first.count(":") != 2:
        problems.append(f"clock did not tick with seconds: {first!r} -> {second!r}")
    context.close()

    context = browser.new_context(extra_http_headers={"Accept-Language": "en"})
    context.clock.install()
    page = context.new_page()
    _login(page, walk, "demo_student")
    until = page.evaluate(
        "() => Math.min(...[...document.querySelectorAll('[data-countdown-to]')].map(e =>"
        " Date.parse(e.dataset.countdownTo) - Date.parse(document.body.dataset.serverNow)))"
    )
    if until is None or until <= 0:
        problems.append("no running countdown on the student dashboard")
    else:
        try:
            with page.expect_navigation(timeout=10_000):
                left = int(until) + CLOCK_STEP
                while left > 0:  # the fake clock takes at most a 32-bit jump at a time
                    page.clock.fast_forward(min(left, MAX_JUMP))
                    left -= MAX_JUMP
                page.clock.run_for(RELOAD_WAIT)
        except PlaywrightError:
            problems.append("countdown reached zero but the page did not reload")
    context.close()
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    parser.add_argument("--password", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--axe", help="path to axe.min.js (optional)")
    parser.add_argument("--roles", nargs="*", default=list(ROLES))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    walk = Walk(args.base, args.password, args.out, args.axe)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for role in args.roles:
            for width in WIDTHS:
                for theme in ("light", "dark"):
                    for language in ("bn", "en"):
                        _combo_pages(browser, walk, role, width, theme, language)
        clock = _clock_checks(browser, walk)
        browser.close()
    problems = [r for r in walk.results if r.problems]
    report = {
        "pages": len(walk.results),
        "pages_with_problems": len(problems),
        "clock": clock,
        "results": [asdict(r) for r in problems],
    }
    (args.out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"{len(walk.results)} pages, {len(problems)} with problems, clock: {clock or 'ok'}")
    return 1 if problems or clock else 0


if __name__ == "__main__":
    sys.exit(main())
