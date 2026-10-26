# Master prompt for Claude Code

Duita prompt ache. Prothomta (**Kickoff**) ekbar paste koro, Claude bujhechhe kina check koro. Tarpor ba Path A (ekta ekta P-file) ba Path B (**Autopilot**) chalao. Ei duita prompt-i English-e, karon Claude Code-er instruction English-e shobcheye nirbhul kaj kore.

Prerequisite: project folder-e `CLAUDE.md`, `docs/`, `design/` copy kora ache (README_START_HERE.md dekho).

---

## 1. Kickoff prompt (paste once, then check the answer)

```text
You are the lead engineer on the "Teacher Feedback System" (TFS), a bilingual (Bangla/English) web application for a university. Build it with Python and Django.

## Mission
Each semester, at fixed intervals ("rounds"), every student gives anonymous feedback on each course they are enrolled in and on that course's teacher. Teachers, heads of department (HOD) and administrators then read well-structured, trustworthy results. The system must be secure, genuinely anonymous, beautiful on a phone, and simple for an administrator to run for a whole semester.

## Users
- Student: signs up with a pre-registered student ID plus a one-time activation code, receives a unique non-guessable username, and sees only the courses and teachers of their own level/term.
- Teacher: signs up with a pre-registered teacher ID; sees results for their own courses only.
- HOD: a teacher with the HOD flag for one department; sees that department only, and is one of only two roles that may see Student IDs (the other is Admin).
- Admin: does everything: academic structure, ID registry, enrollment, teacher assignment, results, promotion, question bank, feedback rounds, moderation, settings.

## Requirements (all mandatory)
R1  Three account types (student, teacher, admin) with HOD as a department-scoped role inside teachers.
R2  At signup the ID must match the admin-created registry. Each ID gets one unique username. A Student ID is visible only to the Admin and to the HOD of that student's own department, enforced in queries, exports and logs, not only in templates.
R3  The student sets their level/term; the dashboard then shows only that level's courses and course teachers. The student profile page must be excellent (see design/student_dashboard.html).
R4  The feedback form mixes rating and other questions. A student cannot submit until every required question is answered (client hint, server enforcement).
R5  Teachers see feedback grouped by question, in the original question order, with every answer for a question shown together; rating questions show the average and the star distribution. Add whatever else makes this report more useful (see design/teacher_report.html).
R6  An automatic answer filter removes abusive words and empty or meaningless text (English, Bangla, Banglish).
R7  High security throughout: hashing, encryption, rate limiting, strict CSP, audit log, least privilege, two-factor for Admin and HOD.
R8  One feedback per student per course per round; no feedback for other teachers or departments; no proxy submission.
R9  Admin and HOD dashboards as designed (design/admin_dashboard.html).
R10 The admin adds students by level/term, assigns teachers to courses, enters results, and the system decides automatically who is promoted, retained, or promoted with retakes. The question list and rating topics will be provided later in docs/QUESTION_BANK.md; build the machinery now.

## Non-negotiables
- Anonymity is architectural: no code path may link an answer to a student (CLAUDE.md rule 1, BLUEPRINT section 5.2).
- Deny by default, server-side validation as the source of truth, every string translatable, no secrets in code or logs.
- The owner develops on Windows (D:\Git\Teachers_Feedback_System). Everything must work from PowerShell; keep Linux/CI working.
- Visual design is not yours to improvise: reproduce design/*.html (tokens, layout, Bangla and English, light and dark, mobile first at 360px, WCAG AA).
- You may improve the plan. If you find a flaw, a missing requirement, or a better approach, say so in one short note and proceed with the safest option.

## How we will work
Work happens in slices, one file in docs/prompts/ at a time (P01 to P21). Each slice: implement completely, write tests, run lint and tests, commit, stop. Read only the BLUEPRINT sections a prompt names. Keep replies short.

## Your task right now (do NOT write code yet)
1. Read CLAUDE.md, docs/BLUEPRINT.md, docs/SUPPORT_PROMPTS.md, and open design/index.html with its four pages and tokens.css.
2. Reply with exactly:
   a) Your understanding in at most 10 lines.
   b) The three biggest technical risks and how the plan handles each.
   c) Any contradiction or gap you found between this brief, CLAUDE.md, the BLUEPRINT and the prompts, with a recommended fix.
   d) The assumptions in BLUEPRINT section 9 that you consider risky.
   e) "Ready for P01" when done.
```

---

## 2. Autopilot prompt (paste after you are happy with the Kickoff answer)

Use Opus or Sonnet with a larger budget; it runs for a long time. You can stop it at any moment and later continue with the **Resume** prompt in `SUPPORT_PROMPTS.md`.

```text
Execute the build plan end to end, one prompt file at a time, in this order:
P01 through P21 in docs/prompts/.

For each prompt file:
1. Re-read CLAUDE.md and only the BLUEPRINT sections the prompt names.
2. Implement the slice completely. No TODO stubs, no dead code, no placeholder data except where the prompt says so.
3. Write the tests the prompt requires.
4. Run: ruff check ., ruff format --check ., python manage.py check, pytest -q. Fix every failure before continuing. If a failure is caused by a flaw in the plan, fix the plan file too and say so in one line.
5. Commit with a conventional message (feat(scope): ...). Do not push.
6. Print at most 4 lines: prompt id, what was added, test count, anything the owner must decide.
7. Keep context small: do not re-print files, do not paste logs.

Stop and wait for me when:
- a prompt says "Show plan first" (P08, P09, P12): present a plan of at most 20 lines and wait for my approval;
- tests still fail after two honest attempts;
- a decision is irreversible or changes the anonymity model or the permission table;
- you finish P21, then print the final release checklist.

Never weaken a test to make it pass. Never commit secrets. Never skip the anonymity tests in P09 and P20.
```

---

## 3. Why this prompt is built this way (short notes for you)
- **Role + mission + users + numbered requirements** gives Claude one unambiguous source of truth; each R-number maps to prompts in BLUEPRINT section 8.
- **"Your task right now (do NOT write code yet)"** forces a comprehension check before any token-expensive work; you catch misunderstandings in minutes, not after P09.
- **Non-negotiables** are the few rules that must never be traded away (anonymity, security, Windows, design fidelity).
- **Gates in Autopilot** (plan approval, repeated failure, irreversible decisions) keep a long unattended run safe.
