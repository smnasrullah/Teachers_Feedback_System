# P08 — Results and auto promotion  (use Plan Mode)
**ROLE:** Senior Django engineer, student-information-systems domain.
**CONTEXT:** P07 done. Read BLUEPRINT §5.3 promotion rule.
**TASK:**
1. `GradeScale` (admin-editable; default 4.00 scale A+ 4.00, A 3.75, A- 3.50, B+ 3.25, B 3.00, B- 2.75, C+ 2.50, C 2.25, D 2.00, F 0.00 — confirm with owner), `Result` (enrollment, grade, points, published). Entry by form and CSV. Term GPA + CGPA calculators (credit-weighted; retake policy setting: latest attempt counts, default).
2. `PromotionRule` (admin-editable): max failed courses, min CGPA, min credits.
3. `services/promotion.py`: `preview(semester)` -> per student promote / retain / promote-with-retakes / graduate (last term); `apply(preview)` in one transaction: update `StudentProfile.level_term` / `academic_status`, create retake enrollments for failed courses.
4. Screens: preview table -> confirm -> apply. Per-student override with mandatory reason. Everything audited.
5. After apply, next semester's course list for promoted students is automatic via enrollment.
**CONSTRAINTS:** Preview must equal applied result exactly (test). Idempotent apply (second apply changes nothing).
**ACCEPTANCE:** Tests for each rule boundary, override, idempotency, retake creation, graduation, GPA arithmetic on known examples.
**STOP:** Show plan first, then implement, commit, stop.
