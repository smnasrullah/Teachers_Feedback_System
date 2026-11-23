# Admin guide: accounts and sign-in

This guide is for the people who run the Teacher Feedback System: the Admin, heads of
department and department office staff who hand out codes and help people who cannot sign in.

## How sign-in works

Every account (student, teacher, head of department, Admin) signs in with a **username and
password**. The username is issued by the system (for example `stu_k7x9a2`). It is not the
student or teacher ID.

The system never sends codes by e-mail or SMS. E-mail and phone fields on an account are
optional and are not used for signing in.

Passwords must have at least 12 characters, must not be a common password, all digits, or close
to the username. Admin and head-of-department passwords also need three of: lower case, upper
case, digits, symbols. Five wrong passwords lock the username for 15 minutes.

The server can also require an authenticator app (a 6-digit code) for chosen roles; see
"Authenticator app (optional, per role)" below. By default no role needs one.

## Giving someone an account

1. Register the ID in **Manage → ID registry** (or import a list).
2. Select the entries and choose **Generate activation codes**. A CSV with one
   `XXXX-XXXX-XXXX` code per ID downloads once. Codes are stored only as hashes, so they cannot
   be shown again; generate new ones if a file is lost.
3. Hand each code to its owner in private.

The person then opens **Create your account** and:

1. enters the ID and the activation code;
2. chooses a password;
3. is signed in straight away and shown their username (also on their **My account** page).

Wrong IDs or codes always get the same message, whatever the reason, and repeated attempts are
rate-limited per IP address and per ID.

## Someone forgot their password: issue a reset code

There is no e-mail reset. Instead the Admin or the person's head of department issues a
one-time **reset code**:

1. **Check who is asking.** Whoever holds the code can set the account's password.
2. Admin: **Manage → Users**, open the account, press **Issue reset code**. Head of department:
   **Password reset codes** in the menu, type the person's ID, press **Issue reset code** (only
   accounts of the department you head; other IDs give "No account you may reset has this ID.").
   Both ask for your own password again if you last entered it more than 10 minutes ago.
3. The code is shown **once**; print it or copy it and hand it over in private. It works for
   24 hours and only once. Issuing it is recorded in the audit log (who, for which account; never
   the code). The person's current password keeps working until the code is used.

The person then opens **Forgot your password?** on the login page, enters their ID and the code,
and chooses a new password. That signs the account out on every device and clears any login
lockout. Issuing a new code replaces an unused earlier one. Revoking the ID in the registry also
cancels a pending code.

Reset codes cannot be issued for Admin accounts or for your own account.

## Someone forgot their username

It cannot be recovered without signing in. Look it up for them: search **Manage → ID registry**
for their exact ID; the **Account** column shows the username and links to the account. The
username is also shown on their own **My account** page.

## Admin accounts

Admins are created on the server with `python manage.py create_admin`. An Admin who forgets the
password changes it on the server with `python manage.py changepassword <username>`; there is no
screen that resets another Admin's access.

## Authenticator app (optional, per role)

The server owner can require an authenticator app for some roles with one environment line, for
example `TOTP_REQUIRED_ROLES=admin,hod` (see `docs/SECURITY.md`). For those roles:

- sign-up adds a step: install an authenticator app (Google or Microsoft Authenticator), scan the
  QR code (or type the key under it), type the 6-digit code, and save the 8 one-time
  **recovery codes**;
- every login asks for the current 6-digit code (or one recovery code) after the password;
  accounts without an authenticator set one up at their next login;
- **My account → Authenticator and recovery codes** shows how many recovery codes are left and
  lets the person make new ones or move to a new phone (both need the password and a current
  code);
- a lost phone with no recovery code left: issue a reset code as above; choosing the new password
  also removes the old authenticator, and a new one is set up at the next login.

## Development only: reading a code without a phone

When a role requires the authenticator, a developer can print an account's current code:

```powershell
python manage.py totp_code <username>
```

It refuses to run unless `DEBUG` is on and `DJANGO_SETTINGS_MODULE` is `config.settings.dev`, so
it cannot work on a server. It needs a secret stored on the account, which exists after sign-up
or once the first-login setup page has been opened. During sign-up itself the secret is not
stored yet: scan the QR code, or feed the key shown under it to any TOTP tool.
