# P01 — Scaffold
**ROLE:** Senior Django engineer.
**CONTEXT:** Empty repo containing CLAUDE.md, docs/, design/ and dotfiles (`.gitignore`, `.gitattributes`, `.editorconfig` — keep them). Read BLUEPRINT §1 and §7 only.
**TASK:**
0. Run `python --version`, `git --version`, `docker --version` and report anything missing in one line (Docker is optional locally, required for CI/prod).
1. Create Django 5.2 project `config/` with settings split `base/dev/prod` (django-environ), `.env.example` (every variable documented), `apps/` package and the empty apps from §7. `TIME_ZONE="Asia/Dhaka"`, `USE_TZ=True`, `LANGUAGE_CODE="bn"`, `LANGUAGES` bn/en, `LocaleMiddleware`, `LOCALE_PATHS`.
2. `requirements/{base,dev,prod}.txt` with exact pins (latest stable compatible with Django 5.2). `pyproject.toml`: ruff (lint + format), pytest-django, coverage. `.pre-commit-config.yaml` (ruff).
3. Front-end pipeline without Node: `django-tailwind-cli` (Tailwind v4 standalone), `static/src/tokens.css` placeholder, vendored Alpine.js **CSP build**, HTMX, Chart.js in `static/vendor/` (+ `VERSIONS.md`). WhiteNoise for static. `base.html`: blank themed page, scripts via `{% static %}` only (no inline JS), CSP-nonce-ready, HTMX sends the CSRF token header, `htmx.config.allowEval = false` (set from an external file).
4. `Dockerfile` (python-slim, WeasyPrint native libs + fonts, non-root user) and `docker-compose.yml` (web, db=postgres, redis, celery, beat). Celery wired; `CELERY_TASK_ALWAYS_EAGER=True` in dev settings so Windows needs no worker.
5. `/healthz` returns 200 after checking DB and cache; exposes no config.
6. Cross-platform task runner: `Makefile` **and** `scripts/dev.ps1` with identical targets `run test lint fmt migrate seed`.
**CONSTRAINTS:** No models yet. No placeholder TODOs. Nothing may require bash on Windows.
**DELIVERABLES:** runnable project.
**ACCEPTANCE:** `python manage.py check`, `pytest -q` (1 smoke test), `ruff check .`, `ruff format --check .` pass; `/healthz` 200 via runserver; `docker compose config` validates.
**STOP:** Commit, then stop.
