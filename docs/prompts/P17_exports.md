# P17 — Exports
**ROLE:** Backend engineer.
**CONTEXT:** Dashboards done.
**TASK:** `reports/` with Excel (openpyxl), PDF (WeasyPrint; Bangla font embedded from local TTF; reuse the server-rendered SVG/CSS charts from P14, **no JavaScript charts**), CSV (UTF-8 with BOM so Excel shows Bangla). Exports: teacher course report, HOD department report, admin university report, pending-submission list. Role-scoped through the same permission layer; threshold + after-close rule applied; Student ID column only for Admin/HOD(own dept); every export writes an audit event; CSV/Excel cells starting with `= + - @` are neutralised.
**CONSTRAINTS:** No individual-response linkage or timestamps in any export; comments exported shuffled.
**ACCEPTANCE:** Tests per export per role; Bangla renders in PDF (font embedded check); threshold respected; formula-injection test; WeasyPrint tests skip cleanly without native libs.
**STOP:** Commit, then stop.
