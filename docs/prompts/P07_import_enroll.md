# P07 — CSV import, enrollment, teacher assignment
**ROLE:** Senior Django engineer.
**CONTEXT:** P06 done. Read BLUEPRINT §3 F2 and §5.1.
**TASK:**
1. `Enrollment` (**student_profile**, offering, status regular/retake; unique pair).
2. Generic importer in `academics/services/importers.py`: upload -> validate -> **preview with row errors** -> apply atomically; dry-run; downloadable CSV templates for student IDs (creates registry + `StudentProfile`, optional activation codes), teacher IDs (registry + `TeacherProfile`), courses, offerings, enrollments. Accept UTF-8 and UTF-8-BOM (Excel), size limit 5 MB / 10k rows, strict header check, strip cells starting with `= + - @` unless they are plain negative numbers.
3. Screens: bulk teacher-to-offering assignment grid; enroll students by level/term (select group -> enroll in all offerings of that level/term for the current semester), single enroll/remove, "students missing enrollment" list.
4. `get_current_courses(student_profile)` now uses real enrollment.
5. Audit every import and bulk action (counts only, no raw IDs).
**CONSTRAINTS:** No half-applied imports. 5k-row CSV stays fast (`bulk_create`).
**ACCEPTANCE:** Tests for good/bad CSV, BOM, atomicity, duplicates, formula-like cells, selector correctness.
**STOP:** Commit, then stop.
