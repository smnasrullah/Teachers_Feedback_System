# P04 — Accounts, roles, ID registry
**ROLE:** Senior Django backend engineer.
**CONTEXT:** P03 done. Read BLUEPRINT §3 F1, §5.1 and §5.3.
**TASK:**
1. In `academics` create the minimal shared models first: `Department`, `Program`, `Batch`, `LevelTerm` (name, order, configurable count). P06 adds CRUD and the rest.
2. Custom `User` (role STUDENT/TEACHER/ADMIN, department, nickname, language, avatar, encrypted contact email/phone + blind indexes, `totp_secret` encrypted, `totp_enabled`). HOD is **not** a role: it is a flag on `TeacherProfile` (`is_hod`, `hod_department`); expose `user.is_hod`/`user.hod_department`. Conditional unique constraint: one active HOD per department.
3. `IdRegistry`: `id_type` (student/teacher), `external_id` encrypted + blind index (unique per type), optional encrypted `full_name`, department, status (unclaimed/claimed/revoked), `claimed_by` (nullable OneToOne to User), `activation_code_hash`, `activation_expires_at`, `activation_used_at`.
4. `StudentProfile` (OneToOne registry; program, batch, `level_term`, section, `academic_status` active/graduated/dropped) and `TeacherProfile` (OneToOne registry; designation, photo, `is_hod`, `hod_department`). Both exist **before** signup (created with the registry row).
5. `services/username.py`: unique non-guessable username (`stu_k7x9a2`, `tch_...`), immutable. `services/student_id_policy.py`: `can_view_student_id(viewer, student_profile)` -> Admin always, HOD only if student's department == `hod_department`, others never. Provide queryset helper `with_visible_ids()` and template filter `student_id` (returns masked value when not allowed). Same policy covers `full_name`.
6. `core/uploads.py`: `validate_and_reencode_image()` (type sniff, size cap, Pillow re-encode, strip EXIF, random filename) used for avatars.
7. Admin screens (Admin only): registry list/search/create/edit, bulk activate/revoke claim, **generate activation codes** (plaintext shown/downloaded exactly once as CSV; only the hash is stored), role assignment and HOD assignment (audited). `manage.py create_admin` (interactive; forces strong password; TOTP enrolled at first login).
**CONSTRAINTS:** No signup flow yet. Registry IDs normalised before hashing.
**ACCEPTANCE:** Tests: policy matrix (student, teacher, HOD same/other dept, admin); username unique + immutable; ID stored encrypted (raw column never equals plaintext); no raw ID in any list response for non-admin; one active HOD per dept; upload validator rejects non-images and oversized files.
**STOP:** Commit, then stop.
