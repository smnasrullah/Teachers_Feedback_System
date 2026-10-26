# P20 — Security audit and test hardening  (use Opus)
**ROLE:** OWASP reviewer + QA lead. Treat the code as written by someone else and try to break it.
**CONTEXT:** P01–P19 done. Read BLUEPRINT §5.2 and §5.4.
**TASK:**
1. `tests/security/`: role x URL matrix (every role against every route; expected status table), IDOR checks on every object URL, CSRF, session fixation, open redirect, rate limits, 2FA bypass attempts, activation-code brute force, upload abuse, CSV/Excel injection.
2. `tests/anonymity/`: attempt re-identification via joins, timestamps, ordering, UUID patterns, small classes, live counters, exports, audit log, drafts, error pages. Fix every leak found.
3. Verify no secrets, OTPs, passwords or feedback text in logs/errors. `pip-audit` and `bandit` clean. `python manage.py check --deploy` clean.
4. Run the suite on PostgreSQL (docker compose) including `@pytest.mark.postgres` concurrency tests.
5. Retention command (drafts, old OTPs, audit policy), backup/restore command, key-rotation command + doc, `verify_audit_chain`.
6. Write `docs/SECURITY.md` and `docs/PERMISSIONS.md`.
**OUTPUT:** findings table (issue, severity, fix).
**ACCEPTANCE:** No high/critical left; coverage >= 80% on core apps (`pytest --cov`).
**STOP:** Commit, then stop.
