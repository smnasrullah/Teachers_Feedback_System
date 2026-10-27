# Security notes: authentication

How accounts prove who they are, and what protects each step. Anonymity of feedback is
unaffected by anything here: feedback rows still have no link to an account (CLAUDE.md rule 1).

## Model

- **Every role** (student, teacher, head of department, Admin) uses a password **and** a TOTP
  authenticator (RFC 6238: 6 digits, 30-second steps, SHA-1, as Google and Microsoft
  Authenticator expect).
- There are no e-mail or SMS one-time codes anywhere. Contact fields on `User` are optional,
  encrypted, and used only for notifications.
- Re-authentication before the final feedback submit is password-only, as before.

## Secrets at rest

| Item | Storage |
|---|---|
| Password | Argon2id hash (Django) |
| TOTP secret | `User.totp_secret`, Fernet-encrypted field |
| Recovery codes (8, `XXXXX-XXXXX`) | HMAC blind index only (`RecoveryCode.code_hash`); plaintext shown once |
| Activation codes (`XXXX-XXXX-XXXX`) | HMAC blind index on `IdRegistry`; plaintext only in the response that issues it |
| Sign-up in progress | Session holds the password **hash** and the new TOTP secret, each Fernet-encrypted |
| Authenticator change in progress | Session holds the new secret, Fernet-encrypted, for at most `SECOND_FACTOR_PENDING_SECONDS` |

Nothing above is ever logged or written to the audit log. As a second line of defence the log
scrubber (`apps/core/logging.py`) redacts values named like `password`, `secret`, `token`, `otp`,
`totp` or `*_code`, and anything shaped like an activation code.

## Sign-up (`apps/accounts/services/signup.py`)

1. ID + activation code. `find_claimable` does the same hashing and comparison whether the ID
   exists or not; every failure gets one generic message. Limits: per IP and per hashed ID.
2. Password, validated by role (stronger for heads of department re-enrolling).
3. Authenticator: a new secret is generated server-side, shown as an inline SVG QR code (`segno`,
   no external service) and as a typed key. `complete()` verifies the first code, then, in one
   transaction with the registry row locked (`select_for_update`), creates the account, installs
   the secret, issues recovery codes, claims the row and burns the activation code. Nothing is
   written to the account tables before the code checks out. The confirming step is stored, so
   the same code cannot be replayed at login.

## Login (`apps/accounts/views/auth.py`, `services/login.py`)

- Password first. A correct password only creates a *pending* login in the session (10 minutes);
  no authenticated session exists until the second step passes.
- The second step accepts the current, previous or next 30-second step (clock drift) and only a
  step newer than the last accepted one (`User.totp_last_step`, updated under a row lock), so a
  code cannot be reused. A recovery code is burned by a conditional update.
- Wrong codes are reported to django-axes and count towards the same username lockout as wrong
  passwords. Both steps are also rate-limited per IP and per subject.
- Accounts without an authenticator (created by `create_admin`, or before this model) must enrol
  before the login completes.
- `sessions.problem` ends any authenticated session that did not pass the second factor (fail
  closed).

## Password reset (`services/recovery.py`)

Username + authenticator code (or recovery code), then a new password within the pending window.
Unknown, disabled or authenticator-less accounts run the same code checks against a decoy secret
and get the same message. Failures count towards the axes lockout of that username, so a reset
cannot be used to brute-force codes. A successful reset ends every session and clears the lockout.
Forgotten usernames are not recoverable without signing in; the department or Admin looks them up.

## Lost phone: Admin "Reset access" (`services/registry.reset_access`)

Admin-only, audited (`account.access_reset`, no code in the metadata). It sets an unusable
password, deletes the TOTP secret and recovery codes, ends every session, clears the lockout and
puts a fresh activation code on the **claimed** registry row. A claimed row carries an activation
code only in this state; sign-up then re-enrols the existing account (same username) instead of
creating one, and audits `auth.reenrolled`. Admin accounts and the Admin's own account cannot be
reset this way; revoking the registry entry cancels a pending reset.

## Profile changes

Regenerating recovery codes and moving to a new authenticator both require the password **and** a
current TOTP code. A device change installs the new secret only after a code from it verifies;
recovery codes stay valid.

## Development helper

`python manage.py totp_code <username>` prints the current code. It refuses unless `DEBUG` is true
**and** `settings.SETTINGS_MODULE == "config.settings.dev"`; under `config.settings.test` or
`config.settings.prod` it exits with an error and prints nothing.

## Password-only demo login (development only)

`seed_demo` accounts (`demo_admin`, `demo_hod`, `demo_student`) skip the authenticator code at
login, so a local demo is usable. **Never enable `DEMO_SKIP_SECOND_FACTOR` outside local
development.** It is `False` in `base.py` and `True` only in `dev.py`. The login service
(`login.is_demo_account`) honours it only when all of these hold:

- the flag, `DEBUG` and `SETTINGS_MODULE == "config.settings.dev"`;
- the username starts with `demo_` and the account is tied to a `DEMO-` registry row (the Admin
  has none, so the `admin.created` audit event written by `seed_demo` stands in);
- the peer address (`REMOTE_ADDR`) is `127.0.0.1` or `::1`, and no `X-Forwarded-For` header is
  present, so a LAN, tunnel or proxy never qualifies.

The password, lockout and rate limits still apply; the session is a normal fully authenticated one;
each such login writes the audit event `auth.login_demo_bypass`. System check `core.E004` is an
error when the flag is on with `DEBUG` off or another settings module, so production cannot start
with it. Real accounts (including any made by `create_admin`) are never affected.

## Removed

The e-mail/SMS one-time-code system (the `OneTimeCode` model, its delivery task and backends, the
`OTP_*` settings and the `purge_one_time_codes` command) was removed. Migration
`accounts.0004_remove_one_time_codes` drops the table.
