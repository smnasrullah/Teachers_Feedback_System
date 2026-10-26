# P09 — Feedback core and anonymity  (use Plan Mode)
**ROLE:** Senior engineer, privacy-by-design specialist.
**CONTEXT:** P08 done. Read BLUEPRINT §5.1–§5.2 and CLAUDE.md rules 1,4,5,6.
**TASK:**
1. Models in `feedback/`: `Question` (versioned: `version`, `supersedes`), `FeedbackWindow` (semester, name, opens_at, closes_at, is_active, optional dept/level-term scope; minimal here, UI in P10), `SubmissionReceipt(student_profile, offering, window)` with `UniqueConstraint` and **no time field**, `FeedbackResponse(id=UUID4, offering, window)` and `Answer(id=UUID4, response, question, int_value, choice_value, encrypted_text)` with **no timestamps**, `Draft(student_profile, offering, window, encrypted payload, updated_at)`.
2. `services/submit.py::submit_feedback(student_profile, offering, window, answers, *, reauth_ok)` inside `transaction.atomic()`: insert the receipt first (the unique constraint is the lock; `IntegrityError` -> "already submitted"), check window open via `window.is_open(now)`, scope, enrollment, required answers, answer types/ranges (rating 1–5 etc.), run the filter hook (identity until P11), then write response + answers, delete draft, record an audit event **without content**. Required text that is empty after cleaning raises a field error (never silently dropped).
3. `services/anonymity.py`: `MIN_RESPONSES` guard (floor 3), stable seeded shuffle for comments, `results_visible(window)` (after close).
4. Proxy prevention: re-auth freshness check (<=5 min), ratelimit, audit.
**CONSTRAINTS:** No FK/id/IP/time linking response to a student. Use `select_for_update` where it matters; the concurrency test must run on PostgreSQL (`@pytest.mark.postgres`, skipped on SQLite with a clear reason).
**ACCEPTANCE:** Tests: duplicate/parallel submit creates one row; wrong course/dept/closed window/not enrolled rejected; a test that introspects **all** models and fails if `FeedbackResponse`/`Answer` can reach `User`, `StudentProfile`, `Enrollment` or `SubmissionReceipt` through any forward or reverse relation chain; no datetime fields on those two models.
**STOP:** Show plan first, implement, commit, stop.
