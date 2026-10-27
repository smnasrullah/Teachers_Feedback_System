# Admin guide: accounts and sign-in

This guide is for the people who run the Teacher Feedback System: the Admin and department
office staff who hand out activation codes and help people who cannot sign in.

## How sign-in works

Every account (student, teacher, head of department, Admin) signs in in two steps:

1. **Username and password.** The username is issued by the system (for example
   `stu_k7x9a2`). It is not the student or teacher ID.
2. **A 6-digit code from an authenticator app** on the person's phone (Google Authenticator
   or Microsoft Authenticator). The code changes every 30 seconds. If the phone is lost, one of
   the person's 8 **recovery codes** works instead, once each.

The system never sends codes by e-mail or SMS. E-mail and phone fields on an account are
optional and are not used for signing in.

## Giving someone an account

1. Register the ID in **Manage → ID registry** (or import a list).
2. Select the entries and choose **Generate activation codes**. A CSV with one
   `XXXX-XXXX-XXXX` code per ID downloads once. Codes are stored only as hashes, so they cannot
   be shown again; generate new ones if a file is lost.
3. Hand each code to its owner in private.

The person then opens **Create your account** and:

1. enters the ID and the activation code;
2. chooses a password;
3. installs an authenticator app, scans the QR code (or types the key shown under it) and types
   the 6-digit code. The account is created only when this code is correct;
4. saves the 8 recovery codes (they are shown once; print or copy them) and notes the username.

Wrong IDs or codes always get the same message, whatever the reason, and repeated attempts are
rate-limited per IP address and per ID.

## Someone forgot their password

They can reset it themselves on **Forgot your password?** with their username and a current
authenticator code (or a recovery code). Repeated wrong codes lock the username for the
cool-off time, exactly like wrong passwords.

## Someone forgot their username

It cannot be recovered without signing in. Look it up for them: search **Manage → ID registry**
for their exact ID; the **Account** column shows the username and links to the account. The
username is also shown on their own **My account** page.

## Lost phone: reset access

Use this when someone has neither their phone nor a recovery code. It works for students,
teachers and heads of department. It cannot be used on Admin accounts or on your own account.

1. **Check who is asking.** Resetting gives whoever holds the new code full control of the
   account.
2. Open **Manage → Users**, find the account and open it.
3. In **Reset access**, choose how long the new code is valid and whether you want a printable
   page or a CSV file, then press **Reset access**.

This immediately:

- removes the password, the authenticator and all recovery codes;
- signs the account out on every device;
- clears any login lockout;
- issues a new one-time activation code (shown once) and records the reset in the audit log
  (who did it, for which account; never the code).

Hand the code over in private. The person then follows the normal **Create your account** steps
with their ID and the new code. They keep the same username, history and department; only the
password, authenticator and recovery codes are new. If the code expires before it is used, reset
access again.

Revoking the ID in the registry also cancels a pending reset code.

## Admin accounts

Admins are created on the server with `python manage.py create_admin` and set up their
authenticator at the first login. An Admin who loses their phone signs in with a recovery code
and then uses **My account → Authenticator and recovery codes → New phone**. Keep the recovery
codes of Admin accounts somewhere safe and offline; there is no screen that resets another
Admin's access.

## Managing your own authenticator

**My account → Authenticator and recovery codes** shows how many recovery codes are left and
lets anyone:

- **make new recovery codes** (needs the password and a current code; the old codes stop
  working);
- **move to a new phone** (needs the password and a code from the old phone, then a code from the
  new one; the recovery codes stay the same).

## Development only: reading a code without a phone

On a developer machine you can print an account's current code:

```powershell
python manage.py totp_code <username>
```

It refuses to run unless `DEBUG` is on and `DJANGO_SETTINGS_MODULE` is `config.settings.dev`, so
it cannot work on a server. It needs a secret stored on the account, which exists after sign-up or
once the first-login setup page has been opened (for example for a new Admin). During sign-up
itself the secret is not stored yet: scan the QR code, or feed the key shown under it to any TOTP
tool.
