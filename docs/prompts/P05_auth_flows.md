# P05 — Signup, OTP, login, 2FA, reset
**ROLE:** Senior Django engineer, auth specialist.
**CONTEXT:** P04 done. Read BLUEPRINT §4 (signup stepper), §5.4 only.
**TASK:**
1. Signup stepper (HTMX): enter ID **+ activation code** -> must match an unclaimed, unrevoked registry row and an unexpired unused code -> enter email/phone and verify by OTP -> set password -> account created, registry claimed, activation code burned, username issued and shown (also always visible later on the profile).
2. OTP service: 6 digits, stored hashed, 5-min expiry, max 5 attempts, resend cooldown, constant-time compare; sender interface with `ConsoleBackend` (dev), `SmtpBackend` (prod), SMS interface stub.
3. Login (axes + ratelimit), logout, "log out all devices", role-based redirect to dashboard placeholders. **TOTP (pyotp) mandatory for Admin and HOD** (forced enrolment with QR on first login, 8 single-use hashed recovery codes), optional for others.
4. Forgot password and **forgot username** via OTP to the verified contact; password change; active-session list.
5. Audit: signup, login, failed login, lockout, password change, 2FA enable/disable, recovery-code use.
**CONSTRAINTS:** Generic error messages and equal work for known/unknown IDs (no enumeration, no timing leak). Rate limit per IP **and** per ID-hash. Never log OTP/codes/secrets.
**ACCEPTANCE:** Tests: unknown/claimed/revoked ID or wrong/expired code -> same generic error; OTP expiry, attempts, cooldown; lockout; no enumeration; redirect per role; HOD/Admin cannot reach dashboards without TOTP; recovery code works once.
**STOP:** Commit, then stop.
