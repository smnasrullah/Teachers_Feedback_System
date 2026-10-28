# QA report — P28 full sweep (2026-10-27)

Branch `qa/auto-fix`, created from `feat/totp-everyone` (`ceae991`). The prompt assumed the branch already existed; it did not.

## Summary

| Found | Fixed | Needs decision | Not fixed |
|---:|---:|---:|---:|
| 16 | 15 | 4 | 1 |

Two passes in all. The second pass (crawl, fuzz, query guard, browser walk of 416 pages) found nothing new after the fixes.

| Gate (final) | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | pass / pass (312 files) |
| `manage.py check` | no issues (2 documented ratelimit silences) |
| `manage.py check --deploy` (prod settings, sample env via `tests/prod_env.py`) | no issues |
| `makemigrations --check --dry-run` | no changes |
| `migrate` on a fresh temp DB / on a copy of `db.sqlite3` | ok / ok (already current) |
| `pytest -q` (SQLite) | 1524 passed, 6 skipped (before: 1354 passed, 4 skipped) |
| `pytest -q` on PostgreSQL 16 (throwaway Docker container) | 1514 passed, 7 skipped (run before the last browser tests were added) |
| Route crawl (5 roles × every GET route × en/bn) | no 500, matrix matches §5.3 |
| Browser walk `scripts/qa_walk.py` (5 roles × 360/1440 × light/dark × bn/en, axe-core) | 416 pages, 0 problems; clock ticks with seconds, countdown reloads at zero |
| `pip-audit` (base + prod requirements) | no known vulnerabilities |
| `bandit -r apps config` | 0 High; 2 Medium, both false positives (constant HTTPS URL in `moderation.py:75`, placeholder `0.0.0.0` never bound in `net.py:5`); 8 Low (demo seeding RNG, empty-string settings) |

## Defects

| # | Sev | Where | Root cause | Fix | Guarded by |
|---|---|---|---|---|---|
| D1 | Minor | `templates/accounts/login.html:16`, `templates/components/navbar.html:7`, `templates/accounts/signup/_progress.html:2` | Three `aria-label`s had no Bangla entry, so screen readers spoke English on Bangla pages | `22c2c72` | `tests/qa/test_translations.py` (every gettext string in code and templates has a translated `bn` entry) |
| D2 | Minor | `static/src/art.css:355-366`, `var()` fallbacks at `:129-158` | Literal colours bypassed the art palette | `2d085db` | `tests/test_design_system.py::test_page_css_sets_colours_only_through_custom_properties` |
| D3 | Minor (dev only) | `apps/accounts/models.py:105` | Custom `User` lacked `has_perm`/`has_module_perms`, so every Django admin page returned 500 for every role | `4872c34` | `tests/qa/test_dev_admin.py` |
| D4 | Minor | `templates/accounts/profile.html:9` | Avatar include got `user=`, but the component reads `image`/`label`, so the profile always showed "?" | `fadcba8` | `tests/test_student_ui.py::test_profile_shows_the_users_own_avatar_or_initials` |
| D5 | Minor | `templates/admin_panel/audit_log.html:72` | Empty metadata values rendered as a literal `None` | `756db38` | `tests/test_auditlog.py::test_audit_page_shows_a_dash_for_empty_metadata_values` |
| D6 | Minor | `apps/feedback/models.py` `QuestionCategory.__str__` | Returned the English name only, so question pages showed "Lab" / "Teaching" in Bangla | `a668d7e` | `tests/test_questions_windows.py::test_question_pages_name_categories_in_the_active_language` |
| D7 | Minor | `templates/admin_panel/user_list.html:31` | `department.code\|default` relied on invalid-variable fallback (it breaks with `string_if_invalid`) | `3ddf886` | `tests/qa/test_route_crawl.py` (sentinel check on every page) |
| D8 | **Major** | `apps/academics/services/importers.py:219` | Templates call callables, so each `{{ importer.x }}` built an importer whose `__init__` loads whole tables (7–8 full scans per import page view) | `dc268cd` (`do_not_call_in_templates`) | `tests/test_import_enroll.py::test_import_pages_never_build_an_importer` |
| D9 | Minor | `apps/reports/services/university.py:71`, `apps/feedback/window_views.py:71` | One department query per offering (admin dashboard, analytics, exports); round scope re-queried per offering (preview) | `7c4ce16` | `tests/qa/test_query_counts.py` (no statement shape repeats ≥5 times on any page, any role) |
| D10 | **Major** | `static/src/components.css` (live clock, header) | Live clock added to a full header row: about 370px of content at 360px, so the page scrolled sideways and the avatar was cut off | `705ea9d` | `tests/qa/test_browser_layout.py::test_no_page_scrolls_sideways_on_a_phone` |
| D11 | Minor | `templates/base.html:12`, `static/src/components.css` | Cold-cache layout shift up to 0.36: fonts swapped in late, and the phone clock line appeared after JS | `44d3a92` (preload above-the-fold weights; header reserves the clock line via `:has()`) | `test_browser_layout.py::test_pages_do_not_jump_while_they_load` (the phone case fails without the fix; on a local live server fonts arrive too fast to reproduce the desktop font shift, which the walk covers) |
| D12 | **Major** | `static/src/components.css:503` | `.badge-closed` dark mode: `--muted` on `--border` = 4.04:1, below AA | `500dd13` | `tests/test_design_system.py::test_every_badge_meets_aa_contrast` (computes every badge pair, both themes) |
| D13 | Minor | `static/src/components.css:49` | Tailwind preflight removes underlines, so links in sentences differed by colour alone (axe link-in-text-block) | `802b5f6` | `test_browser_layout.py::test_links_in_running_text_are_underlined` |
| D14 | Minor | `templates/reports/hod_overview.html:128` | Scrollable heatmap could not be reached by keyboard (axe scrollable-region-focusable) | `848538e` | `tests/test_hod_panel.py::test_the_wide_heatmap_can_be_scrolled_from_the_keyboard` |
| D15 | Minor | `templates/admin_panel/home.html:8`, `templates/reports/hod_overview.html:8`, `templates/reports/dashboard.html:7`, `templates/reports/overview.html:7` | At 360px the title shrank to 97px beside the semester chips | `a70bc2e` | `test_browser_layout.py::test_page_titles_keep_their_width_beside_the_semester_chips` |
| P1 | Minor (perf) | `apps/analytics/services.py:222` | Analytics count responses per slice (each course/department) to apply `MIN_RESPONSES`, so the first uncached view is linear in courses. Results are cached per round version | **Not fixed**: batching means redesigning the anonymity-sensitive analytics layer, beyond a minimal fix | Allowed by name only in `tests/qa/test_query_counts.py` (`SLICE_GATE`); any other repeat fails |

## New QA tests (`tests/qa/`)

- `test_route_crawl.py`: every URL × 5 roles × en/bn with the §5.3 status matrix spelled out. A new route fails until it gets an expectation. HTML pages are checked with `string_if_invalid` set to a sentinel, plus raw `None`/`{{`/`Traceback`, plus English catalogue strings on Bangla pages.
- `test_idor.py`: other teacher's course (pages, export, note, report-comment), other department (export, pending list, `?department=` tampering), course not taken (form, draft, precheck), someone else's notification.
- `test_form_fuzz.py`: every POST endpoint as its owning role with empty / 20 000-char / XSS+SQL-like / wrong-type input. No 5xx, no reflected or stored unescaped markup, no English in Bangla error pages. Every route rejects a POST without a CSRF token, for every role.
- `test_identity_exposure.py`: student/teacher/HOD crawl of every page and every CSV/XLSX export finds no Student ID or full name the role may not see (§5.3 row 1), with a positive control.
- `test_query_counts.py`, `test_browser_layout.py`, `test_translations.py`, `test_dev_admin.py`, as listed above.

Phase 3 rules were already well covered by existing tests and all pass, so no new defects there:
- duplicates (DB constraint + `select_for_update`; the parallel test passed on PostgreSQL)
- required answers, closed/upcoming rounds, results only after close and above `MIN_RESPONSES` incl. exports and comments
- no relation path from feedback to a person, filter, semester dates, Roman terms, promotion
- session idle/absolute timeout, single session, lockout and rate limits, demo features off in production, audit hash chain

In the browser:
- **Student:** a submitted form is sealed, and a re-POST returns 409.
- **Teacher:** the report draws its chart and the CSV downloads.
- **Admin:** a new category is saved and listed.

## Needs decision

1. **Moderation shows single comments early.** The admin dashboard and moderation queue show individual flagged comments while a round is open and regardless of `MIN_RESPONSES`. The writer stays hidden, but for a small class this weakens hard rule 6 ("comment lists hide below MIN_RESPONSES everywhere"). Keep it, since moderation needs it, or hold the queue until close/threshold?
2. **PDF links that 503.** PDF export links show even when WeasyPrint's native libraries are missing; clicking gives a plain-text 503. Hide the links when PDF is unavailable?
3. **Sign-up and recovery while signed in.** `/signup/`, `/password/forgot/` and `/username/forgot/` open for signed-in users, while `/login/` redirects them. Redirect these too?
4. **Over-eager log scrubber.** It redacts harmless values such as static font file names (`/static/fonts/[REDACTED].woff2`) and whole axes messages. That's privacy-safe but makes ops logs harder to read. Tune it?

## Checks that could not be run as asked

- **`makemessages -l bn`:** GNU gettext isn't installed on this Windows machine. It's replaced by `tests/qa/test_translations.py` (AST for Python, Django's `templatize` for templates, compared with the catalogue; fuzzy/untranslated entries: 0).
- **WeasyPrint PDF tests:** 2 skipped (native libraries missing). PDF links return the designed 503 here.
- **PostgreSQL-only tests:** skipped on SQLite. They were run once on a throwaway PostgreSQL 16 container, not in CI.
- **axe-core:** run from a dev-only copy in a scratch directory, not vendored into the repo. `scripts/qa_walk.py --axe <path>` takes it as an option.

## Coverage

| App | Before | After |
|---|---:|---:|
| academics | 97.2% | 97.2% |
| accounts | 94.9% | 95.6% |
| analytics | 99.7% | 99.7% |
| auditlog | 95.8% | 95.8% |
| core | 95.4% | 95.4% |
| enrollment | 92.8% | 94.6% |
| feedback | 96.5% | 96.8% |
| notifications | 94.2% | 94.2% |
| reports | 96.4% | 97.0% |
| **Total** | **97% (271 of 9231 missed)** | **97% (248 of 9237 missed)** |

## Remaining risks

1. **P1 analytics load:** the first view of analytics and dashboards after a round closes runs one gate query (plus two tally queries when above threshold) per course. Watch it at university scale.
2. **Moderation before close** (decision 1) is the one place a comment is seen outside the `MIN_RESPONSES` rule.
3. **The browser walk is a manual script,** not in CI. Layout, contrast and keyboard regressions outside the pages in `test_browser_layout.py` are caught only when someone runs `scripts/qa_walk.py`.

Screenshots of the final state: `docs/qa/screenshots/` (10 pages, every role, phone and desktop, light and dark, bn and en).
