# Demo accounts and demo data

For development only. `seed_demo` refuses to run unless `DEBUG` is on and the settings module is
`config.settings.dev`, so no demo password or authenticator key can exist anywhere else.

## Seed and reset (Windows PowerShell)

```powershell
scripts/dev.ps1 migrate
scripts/dev.ps1 seed                              # random password, printed once
scripts/dev.ps1 seed --password "Your-Own-Pass-1" # or set DEMO_PASSWORD in the environment
scripts/dev.ps1 seed --reset                      # remove the demo data and stop
scripts/dev.ps1 run
```

Linux/CI: `make seed` and `make seed ARGS="--reset"`.

- Running it twice changes nothing. A step that was done is skipped, so you can run it after a reset
  or after the database was migrated again.
- The password, the three authenticator setup keys and two spare sign-up pairs are printed to the
  terminal at the end, and nowhere else (no file, no log, no audit event). The setup keys are
  printed on every run; the password only when it was generated or given; the spare pairs only
  right after they were created (use `--reset` and seed again for new ones).
- `--reset` deletes the `demo_` accounts, the `DEMO-` IDs and everything attached to them
  (enrolments, results, receipts, responses, notices, ...). The academic rows it created
  (departments, courses, semesters, ...) and the demo questions are removed only when nothing
  else uses them, so data of your own with the same name is left alone. Audit events are
  append-only and stay.
- If your bank already holds questions of your own, they are kept and the demo submissions answer
  those. Seeding stops with a message when another semester is already marked as current.

## Accounts

| Username | Role | Notes |
| --- | --- | --- |
| `demo_admin` | Admin | Sees every screen and every department. |
| `demo_hod` | Teacher, head of CSE | Also teaches Discrete Mathematics (Fall) and Linear Algebra (Spring). |
| `demo_student` | Student, CSE, Level 2 Term 1 | Nickname "Demo Student"; enrolled in all six Level 2 Term 1 courses of Fall 2026. |

Every account signs in with its authenticator. Add each printed setup key to an authenticator app
(time-based, 6 digits), or read the current code from the terminal:

```powershell
python manage.py totp_code demo_student
```

On the login page (only while `DEBUG` is on) a collapsed "Demo accounts" box lists the three
usernames and this hint. It never shows a password or a key.

## What the data contains

- Departments CSE and EEE (EEE proves cross-department denial), one program and batch each.
- **Fall 2026** (current): six CSE Level 2 Term 1 courses (theory and lab) and an **open** round,
  "Fall 2026 mid-term feedback". `demo_student` has two forms sealed and four pending; most other
  students have some pending, and the two spare students have none.
- **Spring 2026** (previous): four CSE Level 1 Term 2 courses and two EEE courses with published
  results, and a **closed** round, "Spring 2026 end-of-term feedback". Every CSE offering has at
  least nine responses; the two EEE offerings have fewer than `MIN_RESPONSES`.
- 15 CSE students (including `demo_student`) were promoted from Spring through the real promotion
  service. Six EEE students are still waiting: Promotion shows promote, retain, promote with
  retakes and graduate for Spring 2026.
- Four more teachers, 14 + 6 synthetic students (`DEMO-S002` ... `DEMO-S015`, `DEMO-E001` ...
  `DEMO-E006`) with unused activation codes. The last two CSE students (`DEMO-S014`, `DEMO-S015`)
  are the spare pairs for testing a real sign-up at `/signup/`.
- A demo question bank of 19 questions in 6 categories (rating, agreement, choice, yes/no, text;
  theory-only and lab-only items), with Bangla and English wording.
- Comments in English and Bangla, some with abusive words: the filter removed the words and the
  comments wait in Moderation (one approved and one hidden already, to fill those tabs).
- Two "action taken" notes, a few notifications per account, and audit events from the normal
  code paths. Every response was created by `submit_feedback` with a synthetic student.

## Tour: student (`demo_student`)

1. Sign in; the dashboard lists six Fall 2026 courses: two Sealed (submitted), four Pending.
2. Open a pending course. Answer the questions; theory and lab courses ask different ones.
3. Save a draft, reload the page, and see the draft come back.
4. Submit (the page asks you to confirm the password again) and see the course become Sealed.
5. Try to open a submitted form again: it cannot be changed.
6. Open the bell: three notices, one already read. Switch language and theme in the top bar.
7. Open My account: the nickname is "Demo Student"; two-factor shows enabled.
8. **Must not be visible:** any Student ID (yours or anyone's), any other student's name.
9. **Must not be visible:** other students' answers, or who wrote any comment.
10. Edit the URL to a course you are not enrolled in (an EEE offering): you get 404, not the form.

## Tour: head of department (`demo_hod`)

1. Sign in; the HOD dashboard shows the department overview (pick the closed Spring 2026 round).
2. Look at the heatmap and the low-rating alert (one teacher is rated low on purpose).
3. Open a CSE course report: rating bars, radar chart, comments (cleaned) in a stable, shuffled order.
4. Find the "action taken" notes on the courses that have them.
5. Open Pending: CSE students owing forms in the open round, **with their Student IDs**.
6. Send a reminder to one student; the audit page shows who queued it.
7. Open Teacher > My courses: your own two courses, with your own reports.
8. **Must not be visible:** EEE data. `/teacher/courses/<EEE offering>/<round>/` answers 403, and
   EEE students are only counted, never listed.
9. **Must not be visible:** who wrote a comment, or when. No timestamps appear on answers.
10. **Must not be visible:** results of the open round (they appear only after it closes).

## Tour: admin (`demo_admin`)

1. Sign in; the dashboard shows people, participation of the open round and alerts.
2. Registry: 26 `DEMO-` IDs; the spare students show an active activation code.
3. Academics > Courses/Offerings and Teaching: reassign a teacher.
4. Results and Promotion: choose Spring 2026 and read the four outcomes; set an override.
5. Rounds and Questions: open the two rounds and the 19 questions.
6. Moderation: the queue holds comments the filter cleaned; approve or hide one.
7. Analytics: the university report; open an EEE course and see "Not enough responses to show this."
8. Notifications and Settings: edit a template, change `MIN_RESPONSES` (never below 3).
9. Audit log: events from seeding; verify the hash chain.
10. **Must not be visible:** who wrote a comment; passwords, authenticator keys or activation codes
    anywhere (only the terminal showed them). Student IDs and names are visible here by design.
