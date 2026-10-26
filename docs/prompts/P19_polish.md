# P19 — Bilingual, responsive, accessibility
**ROLE:** UI/UX designer + front-end engineer.
**CONTEXT:** All features exist.
**TASK:**
1. Complete `locale/bn` for every string (`makemessages`, `compilemessages`); per-user language persists; Bangla numerals + dates option.
2. Responsive audit at 360, 768, 1280: sidebar -> bottom/drawer, tables -> cards, charts resize, no horizontal scroll.
3. Accessibility: AA contrast (verify with the token table), keyboard paths, skip link, ARIA live regions, form error association, screen-reader friendly star rating, reduced motion.
4. Skeletons, toasts, empty states, micro-interactions; dark-mode unreadable-text sweep.
**OUTPUT:** `docs/qa_report.md` with issues found and fixed.
**ACCEPTANCE:** Every page renders in both languages; automated axe/Lighthouse accessibility >= 90 on main pages if a headless browser is available, otherwise a documented manual checklist.
**STOP:** Commit, then stop.
