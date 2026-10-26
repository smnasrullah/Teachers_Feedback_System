# P10 — Question bank and feedback windows
**ROLE:** Senior Django engineer.
**CONTEXT:** P09 done. The real questions come later (docs/QUESTION_BANK.md).
**TASK:**
1. Question admin UI: text EN+BN, category (Teaching, Course Content, Lab, Assessment, Behaviour, Overall — admin-extendable), type (rating, likert, choice, yesno, text), options EN+BN, required, order (drag), active, applies (theory/lab/all). Duplicate and activate/deactivate. **Versioning:** once a question has answers, type/options/text are read-only; "Edit" creates a new version and deactivates the old one.
2. `manage.py load_questions docs/QUESTION_BANK.md`: parse the markdown table (Bangla safe, escaped `\|`), upsert idempotently, report skipped rows with reasons; also read the "Rating topics" list as categories. Seed 12 neutral placeholder questions only if the table is empty.
3. Window admin UI: semester, round name, open/close datetime (Asia/Dhaka), active, optional scope (departments / level-terms), preview; rounds in the same scope cannot overlap. Status is **computed** from datetimes (`upcoming/open/closed`); Celery beat is only for notices/housekeeping. Closed windows are rejected by the server.
4. Audit all changes.
**ACCEPTANCE:** Tests: parser (including Bangla and malformed rows), upsert idempotency, versioning rule, overlap validation, window status at boundary instants (frozen time), required flag respected by submit.
**STOP:** Commit, then stop.
