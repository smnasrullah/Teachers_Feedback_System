# P18 — Notifications and reminders
**ROLE:** Backend engineer.
**CONTEXT:** Windows + receipts exist.
**TASK:**
1. In-app notification model + bell dropdown with unread count (HTMX).
2. Email sender + SMS-ready interface; admin-editable templates (EN+BN) with variables; test-send button.
3. Celery beat reminders to students with pending feedback: round opened, 3 days left, 24 hours left, last hour (configurable). Skip students who already submitted (use receipts). Quiet hours (default 22:00–07:00 Asia/Dhaka) for email/SMS; in-app always.
4. HOD "send reminder" action from P15; teacher/HOD notice "results available" when a round closes.
5. Delivery status log without message content.
**ACCEPTANCE:** Tests with frozen time; submitted students never reminded; templates render in both languages; quiet hours respected.
**STOP:** Commit, then stop.
