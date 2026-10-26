# P03 — Security core
**ROLE:** Application-security engineer.
**CONTEXT:** Read CLAUDE.md hard rules and BLUEPRINT §5.3–§5.4.
**TASK:**
1. `core/encryption.py`: `EncryptedTextField`/`EncryptedCharField` (Fernet, `MultiFernet` rotation, keys from env), plus `blind_index(value, purpose)` (HMAC-SHA256 with a **separate** key, input normalised: strip, NFKC, casefold) for equality lookups and unique constraints.
2. `core/permissions.py`: role constants, `role_required`, class mixins, object-level helper, deny-by-default; a test that fails if any URL lacks a permission decorator (explicit allow-list for public pages).
3. `core/middleware.py`: single active session per user, idle + absolute session timeout, security headers (CSP **with per-request nonce**, HSTS, X-Frame-Options, Referrer-Policy, Permissions-Policy, `Cache-Control: no-store` on authenticated pages), request-id.
4. Settings: Argon2id first hasher, Secure/HttpOnly/SameSite cookies, session rotation on login, password validators (min 10, common, numeric, user-similarity), django-axes, ratelimit defaults (Redis cache in prod). Django `admin/` app **not installed** in prod.
5. `core/logging.py`: logging filter that scrubs OTPs, passwords, tokens, activation codes, and long free text; JSON logs in prod.
6. `auditlog`: append-only `AuditEvent` (actor, role, action, object, IP, UA, date, metadata JSON, `prev_hash`/`hash` chain). `audit.record()` helper. Block update/delete in `save/delete` and queryset `update/delete`; add a migration that revokes UPDATE/DELETE for the app DB role on PostgreSQL where possible. Never store secrets or feedback text. `manage.py verify_audit_chain`.
**ACCEPTANCE:** Tests prove encryption roundtrip + key rotation, blind-index determinism, deny-by-default, audit rows immutable and chain verifiable, headers + nonce present, log scrubber works. `python manage.py check --deploy` clean with prod settings.
**STOP:** Commit, then stop.
