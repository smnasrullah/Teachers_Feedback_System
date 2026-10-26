# P21 — Release
**ROLE:** DevOps + technical writer.
**CONTEXT:** All tests green.
**TASK:**
1. Production Dockerfile (multi-stage, non-root), prod compose, gunicorn + nginx conf (TLS-ready, security headers, static/media), maintenance mode, `/healthz`.
2. GitHub Actions `ci.yml`: ruff, tests on PostgreSQL + Redis services, pip-audit, bandit, build.
3. `seed_demo`: 1 admin, 2 HODs, 6 teachers, 60 students, courses, enrollments, a closed and an open round, sample feedback, printed activation codes for demo students.
4. Docs: `README.md`, `docs/DEPLOYMENT.md` (env vars, key generation, backups, first admin), `docs/ADMIN_GUIDE.md` (full semester workflow step by step), `docs/USER_GUIDE.md` (student + teacher + HOD, EN+BN).
**ACCEPTANCE:** Fresh clone + `.env.example` -> `docker compose up` works; CI green; a new admin can run one semester from the guide.
**STOP:** Final checklist, then stop.
