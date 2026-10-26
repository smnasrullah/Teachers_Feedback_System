# P15 — HOD panel
**ROLE:** Full-stack engineer.
**CONTEXT:** P13–P14 done. Read BLUEPRINT §4 and §5.3. **Layout per `design/admin_dashboard.html` (department-scoped).**
**TASK:**
1. Department overview: stat tiles, response rate per course/teacher, rating ranking, low-rating alert cards (configurable threshold), category heatmap, trends. Scope = offerings whose `course.department` is the HOD's.
2. Drill-down to any teacher's offering in scope (reuse teacher report, read-only) and their "action taken" notes. HOD also has their own teacher view for courses they teach.
3. Pending-submission list with Student ID (via `StudentIdPolicy`): own-department students listed with ID; other-department students only counted. Filter by course and level/term. "Send reminder" queues a notification (wired in P18) without revealing who else is pending.
4. HOD department audit view (own department only).
**ACCEPTANCE:** Tests: other department -> 403; IDs visible only here (and Admin); cross-department student never listed with ID; no authorship info in any HOD view.
**STOP:** Commit, then stop.
