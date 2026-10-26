# P12 — Student dashboard and feedback form  (use Plan Mode)
**ROLE:** Senior UI/UX designer + full-stack engineer.
**CONTEXT:** P09–P11 done. Read BLUEPRINT §4 and §6. **Match `design/student_dashboard.html` and `design/feedback_form.html`.**
**TASK:**
1. Student dashboard as designed: profile card (avatar, nickname, dept, batch, level/term, semester, username), progress ring "x of y", round countdown, course cards (course, teacher name + photo, status badge Pending/Submitted/Window closed), anonymity note. Student ID hidden unless `SHOW_OWN_ID_TO_STUDENT`. Profile page: nickname, avatar, language, theme, password, sessions, 2FA — nothing else editable.
2. Feedback form from the question bank (matching theory/lab), grouped by category, star-rating component, sticky progress bar. All required answered, else block, highlight and scroll to the first missing (client), revalidated on the server; text pre-check via `preview_clean`. Warning "don't write your name or personal details".
3. Draft autosave (HTMX), final step: re-auth modal + "final and anonymous" confirmation, then thank-you page.
4. Proxy-prevention UX: new-device notice, session-conflict message.
5. Empty / upcoming / closed / not-enrolled / already-submitted states.
**ACCEPTANCE:** Django test-client HTML tests: only enrolled courses visible; other course URL -> 403/404 without leaking existence; second submit blocked; no Student ID in any student page; works at 360px (manual check noted in report).
**STOP:** Show plan, implement, commit, stop.
