# P16 — Admin panel and university analytics
**ROLE:** Full-stack engineer.
**CONTEXT:** P06–P15 done. Read BLUEPRINT §4. **Match `design/admin_dashboard.html`.**
**TASK:**
1. Admin home: tiles (users, active round, participation), quick actions (Import, Open round, Promote, Questions), charts, recent audit, moderation queue count.
2. University analytics: participation, rating distribution, department comparison, top/bottom courses, time series, filters (semester, department, level/term, round).
3. Moderation queue: flagged comments (cleaned text), approve/hide (never edit text), teacher-reported comments.
4. Audit log viewer: filter by actor/action/date/object, export, chain verification button.
5. System settings page backed by a `SystemSetting` model (cached, audited): MIN_RESPONSES (floor 3), thresholds, SHOW_OWN_ID_TO_STUDENT, PROFANITY_ACTION, RESULTS_VISIBLE, retention, reminder schedule.
**ACCEPTANCE:** Non-admin -> 403 on every URL; filters work; settings change is audited; MIN_RESPONSES below 3 rejected.
**STOP:** Commit, then stop.
