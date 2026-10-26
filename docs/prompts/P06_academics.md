# P06 — Academic structure + admin CRUD
**ROLE:** Senior Django engineer, domain modeller.
**CONTEXT:** P05 done. Read BLUEPRINT §3 F2 and §5.1 only. `Department/Program/Batch/LevelTerm` already exist (P04).
**TASK:**
1. Models: `Semester` (name, dates, `is_current` with conditional unique constraint), `Course` (code, title EN+BN, credit, type theory/lab, department, program, **level_term**, is_elective), `CourseOffering` (course, semester, **teacher -> TeacherProfile**, section; unique course+semester+section; offering department = `course.department`).
2. Admin-only CRUD screens for all academic models, with search, filters, pagination, uniform list/form templates from P02 components; delete protection (PROTECT) with friendly messages.
3. Selector `get_current_courses(student_profile)` returning enrolled offerings of the current semester (stub join until P07).
4. Admin sidebar navigation for these screens; audit every change.
**CONSTRAINTS:** A teacher from another department may be assigned (service courses) but the form shows a warning. Non-admin -> 403.
**ACCEPTANCE:** Admin builds the whole structure from the UI; permission tests; list pages have no N+1 (query-count tests).
**STOP:** Commit, then stop.
