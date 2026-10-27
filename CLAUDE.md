# Teacher Feedback System (TFS) — standing rules
Bilingual (বাংলা/English) Django web app. University students give anonymous feedback on their courses/teachers in periodic rounds each semester. Full spec: `docs/BLUEPRINT.md` (read only the § a prompt names). Visual reference: `design/*.html`.

## Stack (fixed)
Python 3.12 · Django 5.2 LTS (server-rendered) · PostgreSQL (SQLite only for quick local runs) · Tailwind v4 via `django-tailwind-cli` + Alpine.js (CSP build) + HTMX + Chart.js, all vendored in `static/vendor` (no CDN) · Celery + Redis · argon2-cffi, cryptography (Fernet), pyotp, django-axes, django-ratelimit, Pillow, openpyxl, WeasyPrint, whitenoise, gunicorn · pytest, pytest-django, factory_boy, ruff (lint **and** format).
Apps under `apps/`: `core accounts academics enrollment feedback analytics reports notifications auditlog`.
Pin exact versions in `requirements/*.txt` at install time (latest stable that supports Django 5.2).

## Environment
Owner develops on **Windows** (`D:\Git\Teachers_Feedback_System`). Keep everything cross-platform: pathlib, no bash-only scripts without a `scripts/dev.ps1` twin, LF endings (`.gitattributes`), no `make`-only workflows. Timezone `Asia/Dhaka`, `USE_TZ=True`, default language `bn`. Celery runs eager in dev. WeasyPrint-dependent tests skip cleanly when its native libs are missing.

## Hard rules
1. **Anonymity:** `FeedbackResponse`/`Answer` have UUID keys, no relation path to any user/profile/enrollment/receipt, no timestamps, no IP. Only `SubmissionReceipt(student_profile, offering, window)` knows who submitted; it holds no content and no time. Results reach teacher/HOD only after the round closes.
2. **Student ID / full name** visible only to Admin and the HOD of that student's own department. Enforce in querysets, exports, logs, templates via `StudentIdPolicy`.
3. **Deny by default.** Every view uses `apps/core/permissions.py`. Always do object-level checks (IDOR).
4. One feedback per (student, offering, window): DB unique constraint + `transaction.atomic` + `select_for_update`.
5. Server validation is truth; client validation is UX only.
6. Aggregates **and comment lists** hide below `MIN_RESPONSES` (default 5), everywhere incl. exports.
7. Never log passwords, OTPs, activation codes, TOTP secrets, feedback text. Secrets only from env.
8. All user-facing strings via `gettext`; add Bangla in `locale/bn`.
9. Logic in `services/`, views thin. Complete code, no TODO stubs, no dead code.
10. Design: use tokens from `static/src/tokens.css` (BLUEPRINT §6). Never hardcode colors/spacing. Mobile-first 360px, dark mode, WCAG AA, never colour alone. No inline JS/CSS (strict CSP with nonces).
11. No raw SQL with string formatting. No `mark_safe` on user data. No `eval`/`pickle` on input.

## Token-saving workflow
- Read only files you need. Don't re-print files you edited. Don't paste long logs.
- Before saying done: `ruff check . && ruff format --check . && pytest -q` (+ `python manage.py check`). On Windows use `scripts/dev.ps1 test`.
- One prompt = one slice. Commit (`feat(scope): msg`) when green. Never `git push`. Don't start the next prompt.
- Final reply max 8 lines: done / files changed / commands run / open questions.
- Ask only if blocked or the choice is irreversible; otherwise assume and note it in one line.
- If a prompt contradicts BLUEPRINT or these rules, stop and say so in one line.

## Commands
`python manage.py runserver` · `migrate` · `seed_demo` · `create_admin` · `pytest -q` · `docker compose -f docker-compose.prod.yml up -d --build` (server; see `docs/DEPLOY.md`)
Windows: `scripts/dev.ps1 run|test|lint|fmt|migrate|seed`; Linux/CI: `make run|test|lint|fmt|migrate|seed`.
