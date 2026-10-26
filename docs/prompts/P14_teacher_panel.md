# P14 — Teacher panel
**ROLE:** Full-stack engineer + data-viz designer.
**CONTEXT:** P13 done. Read BLUEPRINT §4. **Match `design/teacher_report.html`.**
**TASK:**
1. Overview: my courses for selected semester/round with response rate and average rating.
2. Course report: for each question **in serial order, all answers together**: rating = average + star distribution bars + count per star; choice = % bars; text = cleaned comments in stable-shuffled order with sentiment tag, search/filter, pagination.
3. Extras: category radar, round/semester trend, strengths vs improve, anonymised dept-average comparison, word cloud, "Action taken" note (teacher writes, HOD reads), print view.
4. Bars/stars are rendered **server-side as SVG/CSS** (reused by PDF in P17); Chart.js only for radar and trend.
5. Teacher sees only own offerings; pending = count only.
**ACCEPTANCE:** Tests: cross-teacher access -> 403; threshold hides data; before-close shows "results after round closes"; report order equals question order; no timestamps/identity in HTML.
**STOP:** Commit, then stop.
