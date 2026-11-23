# Security notes: authentication

How accounts prove who they are, and what protects each step. Anonymity of feedback is
unaffected by anything here: feedback rows still have no link to an account (CLAUDE.md rule 1).

## Model

- **Default: password only for every role.** Sign-up is ID + activation code → password →
  account ready (signed in). Login is username + password. Nobody sees a QR code, a code field or
  recovery codes.
- **The authenticator (TOTP) is switchable per role** with one setting, `TOTP_REQUIRED_ROLES`
  (any of `student`, `teacher`, `hod`, `admin`; empty by default). A role in the set gets the
  whole second-factor machinery exactly as before: enrolment at sign-up (or at the next login),
  the 6-digit code at login, 8 recovery codes, the authenticator management page and the session
  check that ends a session which skipped the code. TOTP is RFC 6238: 6 digits, 30-second steps,
  SHA-1, as Google and Microsoft Authenticator expect. A HOD is also a teacher, so `teacher`
  covers heads of department too; `hod` alone covers only them.
- There are no e-mail or SMS one-time codes anywhere. Contact fields on `User` are optional,
  encrypted, and used only for notifications.
- Re-authentication before the final feedback submit is password-only, as before.

### Re-enable the authenticator

For the most powerful roles (recommended for production), one line in the environment:

```
TOTP_REQUIRED_ROLES=admin,hod
```

or, in a settings module, `TOTP_REQUIRED_ROLES = {"admin", "hod"}`. Then restart. Sessions of
those roles that did not pass a code end at their next request (fail closed); their accounts
enrol an authenticator at the next login. With the set empty, `manage.py check` under the
production settings prints warning `core.W001` ("No second factor is required for any role.
Consider requiring it for admin and hod."). An unknown role name is error `core.E005`.

### Stored authenticators while a role is not required

Secrets enrolled earlier stay stored (Fernet-encrypted) and are ignored while the role is not in
the set; they work again if it is re-added. To purge them all (every account then enrols afresh if
its role is later required):

```
python manage.py shell -c "from apps.accounts.models import RecoveryCode, User; RecoveryCode.objects.all().delete(); User.objects.update(totp_secret=None, totp_enabled=False, totp_last_step=0)"
```

## Secrets at rest

| Item | Storage |
|---|---|
| Password | Argon2id hash (Django) |
| TOTP secret (required roles) | `User.totp_secret`, Fernet-encrypted field |
| Recovery codes (8, `XXXXX-XXXXX`) | HMAC blind index only (`RecoveryCode.code_hash`); plaintext shown once |
| Activation and reset codes (`XXXX-XXXX-XXXX`) | HMAC blind index on `IdRegistry`; plaintext only in the response that issues it |
| Sign-up in progress | Session holds the password **hash** (and, for a required role, the new TOTP secret), each Fernet-encrypted |
| Authenticator change in progress | Session holds the new secret, Fernet-encrypted, for at most `SECOND_FACTOR_PENDING_SECONDS` |

Nothing above is ever logged or written to the audit log. As a second line of defence the log
scrubber (`apps/core/logging.py`) redacts values named like `password`, `secret`, `token`, `otp`,
`totp` or `*_code`, and anything shaped like an activation code.

## Passwords (the main control now)

- Validators at sign-up, password change and reset: minimum length **12**, Django's
  common-password list, not entirely numeric, not similar to the username (at sign-up the
  password is checked against the username about to be issued). Admin and HOD accounts also need
  three of: lower case, upper case, digits, symbols (`services/passwords.py`).
- Argon2id hashing; django-axes locks a username + address after `AXES_FAILURE_LIMIT` (5) wrong
  passwords for `AXES_COOLOFF_MINUTES` (15); django-ratelimit limits every auth form per IP and
  per subject (username, hashed ID or session).
- One generic message for an unknown username and a wrong password, with the same work done.
- Auth pages answer `Cache-Control: no-store`; session cookies stay HttpOnly, SameSite=Lax,
  Secure and `__Host-` prefixed in production; single active session, idle and absolute timeouts.

## Sign-up (`apps/accounts/services/signup.py`)

1. ID + activation code. `find_claimable` (via `activation.find_row`) does the same hashing and
   comparison whether the ID exists or not; every failure gets one generic message. Limits: per
   IP and per hashed ID. Only **unclaimed** rows can be signed up; a claimed row's code is a
   password reset code and works only on "Forgot password?".
2. Password, validated by role.
3. Without an authenticator: `complete()` creates the account in one transaction with the
   registry row locked (`select_for_update`), claims the row, burns the activation code and signs
   the person in. For a required role, the authenticator step comes first: a new secret is
   generated server-side, shown as an inline SVG QR code (`segno`, no external service) and as a
   typed key; `complete()` verifies the first code before anything is written, installs the
   secret and issues recovery codes. The confirming step is stored, so the code cannot be
   replayed at login.

## Login (`apps/accounts/views/auth.py`, `services/login.py`)

- Password, through `authenticate` (django-axes). For a role that is not required, a correct
  password signs in.
- For a required role, a correct password only creates a *pending* login in the session
  (10 minutes); no authenticated session exists until the code passes. The code step accepts the
  current, previous or next 30-second step and only one newer than the last accepted one
  (`User.totp_last_step`, under a row lock). Recovery codes burn by conditional update. Wrong
  codes count towards the same axes lockout. Accounts of a required role without an
  authenticator enrol before the login completes. `sessions.problem` ends any session of a
  required role that did not pass the code (fail closed).

## Forgotten password (`services/recovery.py`, `services/registry.issue_reset_code`)

No e-mail, no authenticator: a person-to-person reset code.

- **Issue:** the Admin (any student or teacher account, from **Users → account → Issue reset
  code** or **Password reset codes**) or a head of department (only accounts of the department
  they head, the `StudentIdPolicy` scope; **Password reset codes** in their menu, by ID). Out of
  scope and unknown IDs look the same (404). Never for oneself or for Admin accounts (an Admin
  who forgets the password runs `python manage.py changepassword <username>` on the server). The
  code is `XXXX-XXXX-XXXX`, valid `RESET_CODE_HOURS` (24), stored as a keyed hash on the claimed
  registry row, shown once on a `no-store` page and never logged. Issuing needs a fresh password
  (step-up) and is audited as `account.reset_code_issued` (no code in the metadata). The current
  password keeps working until the code is used.
- **Use:** "Forgot your password?" → ID + reset code → new password (validated). The code is
  checked again and burned in the same locked transaction that sets the password; any stored
  authenticator is forgotten (a required role enrols again), every session ends, the lockout is
  cleared, and `auth.password_reset` is audited. Wrong, used, expired and unknown all get one
  generic message; failures count towards an axes lockout keyed by a hash of the ID (so no
  student ID reaches the axes log lines), and the form is rate-limited per IP and per hashed ID.
- Forgotten usernames are not recoverable without signing in; the department or Admin looks
  them up.

## Step-up for sensitive actions (`services/stepup.py`, `guards.step_up_required`)

Password only, no code. A login counts as a fresh confirmation; after `STEP_UP_SECONDS`
(10 minutes) these ask for the current password again: Admin user management (account detail,
role change, issuing a reset code), password reset codes (Admin and HOD), the pending-students
export (contains student IDs), bulk activation codes (CSV with IDs) and the promotion run.
Password change asks for the current password in its own form. The re-check goes through
`authenticate`, so wrong passwords count towards the axes lockout; it is rate-limited and audited
(`auth.step_up`, outcome only). `next` is followed only inside the site.

## Authenticator management (required roles only)

Regenerating recovery codes and moving to a new authenticator both require the password **and** a
current TOTP code. A device change installs the new secret only after a code from it verifies;
recovery codes stay valid. For other roles these pages redirect to the account page.

## Development helper

`python manage.py totp_code <username>` prints the current code of an account that has an
authenticator (useful once a role is required). It refuses unless `DEBUG` is true **and**
`settings.SETTINGS_MODULE == "config.settings.dev"`; under `config.settings.test` or
`config.settings.prod` it exits with an error and prints nothing.

## Demo second-factor bypass (only matters when a demo role is required)

With `TOTP_REQUIRED_ROLES` empty, the demo accounts simply sign in with username and password and
this bypass has nothing to do. If a role is required, `seed_demo` accounts (`demo_admin`,
`demo_hod`, `demo_teacher`, `demo_student`) of that role skip the code at login, so the sample
roles stay usable. The login service (`login.is_demo_account`) honours it only when all demo
identity checks hold:

- `DEMO_SKIP_SECOND_FACTOR` and either `DEBUG` with `SETTINGS_MODULE == "config.settings.dev"`
  plus loopback access without a forwarding header; an isolated `config.settings.demo`
  deployment; or `DEBUG=False`, `SETTINGS_MODULE == "config.settings.prod"` and
  `PUBLIC_DEMO_ENABLED`;
- the username starts with `demo_` and the account is tied to a `DEMO-` registry row (the Admin
  has none, so the `admin.created` audit event written by `seed_demo` stands in);
- the username is one of the four fixed demo usernames.

The password, lockout and rate limits still apply; each such login writes `auth.login_demo_bypass`.
System check `core.E004` is an error when the flag is enabled outside local dev, isolated demo, or
enabled public demo mode. Real accounts (including any made by `create_admin`) are never affected.

The login page's "Demo accounts" box (usernames, roles, "Fill in" buttons and, when `DEMO_PASSWORD`
still matches all demo accounts, the password) is rendered only in local dev or an explicitly
enabled public demo. Production seeding runs after migrations when public demo mode is enabled, and
the seeder hides credentials from logs in public demo mode.

## Removed

- The e-mail/SMS one-time-code system (the `OneTimeCode` model, its delivery task and backends,
  the `OTP_*` settings and the `purge_one_time_codes` command). Migration
  `accounts.0004_remove_one_time_codes` drops the table.
- The Admin "Reset access" (clear password and authenticator, re-enrol through sign-up) and the
  username + authenticator-code password reset. Both are replaced by the reset code above. A
  registry row still carrying an old "Reset access" code can use it once on "Forgot password?".
