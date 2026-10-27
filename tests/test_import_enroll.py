import csv
import io
import re
from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.urls import reverse
from django.utils import translation

from apps.academics.models import Course, CourseOffering, Semester
from apps.academics.services import assignments, importers, staging
from apps.accounts.models import IdRegistry, IdType, StudentProfile, TeacherProfile, registry_index
from apps.auditlog.models import AuditEvent
from apps.core.csv_safe import clean_cell
from apps.enrollment.models import Enrollment, EnrollmentStatus
from apps.enrollment.selectors import students_missing_enrollment
from apps.enrollment.services import enrollments
from tests.factories import (
    DepartmentFactory,
    LevelTermFactory,
    ProgramFactory,
    make_admin,
    make_hod,
    make_student,
    make_teacher,
    sign_in,
)
from tests.test_academics import make_course, make_offering, make_semester

pytestmark = pytest.mark.django_db

STUDENT_HEADER = "student_id,department,program,level_term,full_name,batch,section"


@pytest.fixture(autouse=True)
def _english():
    """Service-level messages follow the active language, which defaults to Bangla."""
    with translation.override("en"):
        yield


@pytest.fixture
def admin(db):
    return make_admin()


@pytest.fixture
def admin_client(client, admin):
    client.defaults["HTTP_ACCEPT_LANGUAGE"] = "en"
    sign_in(client, admin)
    return client


@pytest.fixture
def world():
    """One department with a program, a level/term and a current semester."""
    department = DepartmentFactory(code="CSE")
    program = ProgramFactory(department=department, code="BSC")
    level_term = LevelTermFactory(level=1, term=1)
    return department, program, level_term, make_semester(current=True, season="summer", year=2026)


def student_in(program, level_term, section="", external_id=None):
    student = make_student(program.department, external_id=external_id)
    student.program, student.level_term, student.section = program, level_term, section
    student.save()
    return student


def run(kind, text, admin, *, apply=True, **options):
    return importers.run(
        importers.IMPORTERS[kind](**options), text, apply=apply, actor=admin, request=None
    )


def student_rows(*rows):
    return "\n".join([STUDENT_HEADER, *rows]) + "\n"


class TestCleanCell:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("=SUM(A1)", "SUM(A1)"),
            ("+cmd", "cmd"),
            ("-cmd", "cmd"),
            ("@user", "user"),
            ("==@+x", "x"),
            ("  = padded ", "padded"),
            ("-5", "-5"),
            ("-0.5", "-0.5"),
            ("-5a", "5a"),
            ("--5", "5"),
            ("Rahim", "Rahim"),
            ("", ""),
        ],
    )
    def test_strips_formula_leaders_but_keeps_plain_negative_numbers(self, raw, expected):
        assert clean_cell(raw) == expected


class TestDecode:
    def test_accepts_utf8_with_and_without_bom(self):
        assert importers.decode("নাম\n".encode()) == "নাম\n"
        assert importers.decode(b"\xef\xbb\xbfa,b\n") == "a,b\n"

    def test_rejects_other_encodings(self):
        with pytest.raises(importers.ImportRejected, match="UTF-8"):
            importers.decode("é".encode("latin-1"))

    def test_rejects_files_over_5_mb(self):
        with pytest.raises(importers.ImportRejected, match="too large"):
            importers.decode(b"a" * (importers.MAX_BYTES + 1))

    def test_rejects_nul_bytes(self):
        with pytest.raises(importers.ImportRejected):
            importers.decode(b"a,b\n\x00\n")


class TestStudentImport:
    def test_good_file_creates_registry_entries_and_profiles(self, world, admin):
        department, program, level_term, _ = world
        result = run(
            "students",
            student_rows(
                "2101001,CSE,BSC,Level 1 Term 1,Rahim Uddin,,A",
                "২১০১০০২,cse,bsc,level 1 term 1,,,",
            ),
            admin,
        )
        assert (result.ok, result.created, result.applied) == (True, 2, True)
        first = IdRegistry.objects.get(external_id_index=registry_index("2101001"))
        assert (first.id_type, first.full_name, first.department) == (
            IdType.STUDENT,
            "Rahim Uddin",
            department,
        )
        assert first.student_profile.section == "A"
        assert first.student_profile.program == program
        assert first.student_profile.level_term == level_term
        assert IdRegistry.objects.filter(external_id_index=registry_index("2101002")).exists()
        assert not first.activation_code_hash

    def test_bom_and_crlf_from_excel(self, world, admin):
        raw = ("﻿" + student_rows("2101001,CSE,BSC,Level 1 Term 1,,,")).replace("\n", "\r\n")
        result = run("students", importers.decode(raw.encode("utf-8")), admin)
        assert result.ok
        assert StudentProfile.objects.count() == 1

    def test_row_errors_are_reported_with_line_numbers_and_nothing_is_saved(self, world, admin):
        text = student_rows(
            "2101001,CSE,BSC,Level 1 Term 1,,,",
            "!!,CSE,BSC,Level 1 Term 1,,,",
            "2101003,NOPE,BSC,Level 1 Term 1,,,",
            "2101004,CSE,NOPE,Level 1 Term 1,,,",
            "2101005,CSE,BSC,Level 9,,,",
            "2101006,CSE,BSC,Level 1 Term 1,,NOBATCH,",
            "2101007,CSE,BSC,Level 1 Term 1",
            "2101008,CSE,BSC,Level 1 Term 1,,,,extra",
        )
        result = run("students", text, admin)
        assert not result.ok
        assert [(e.line, e.column) for e in result.errors] == [
            (3, "student_id"),
            (4, "department"),
            (5, "program"),
            (6, "level_term"),
            (7, "batch"),
            (9, ""),
        ]
        assert IdRegistry.objects.count() == 0
        assert StudentProfile.objects.count() == 0

    def test_duplicates_in_file_and_against_existing_entries(self, world, admin):
        make_student(world[0], external_id="2101001")
        text = student_rows(
            "2101001,CSE,BSC,Level 1 Term 1,,,",
            "2101002,CSE,BSC,Level 1 Term 1,,,",
            "2101002,CSE,BSC,Level 1 Term 1,,,",
            " 2101-002 ,CSE,BSC,Level 1 Term 1,,,",
            "２１０１００２,CSE,BSC,Level 1 Term 1,,,",  # noqa: RUF001 - full-width digits are the point
        )
        result = run("students", text, admin)
        assert [e.line for e in result.errors] == [2, 4, 6]
        assert IdRegistry.objects.filter(id_type=IdType.STUDENT).count() == 1

    def test_formula_like_cells_lose_their_leader(self, world, admin):
        result = run(
            "students", student_rows("2101001,CSE,BSC,Level 1 Term 1,=HYPERLINK(1),,@x"), admin
        )
        assert (result.ok, result.sanitized) == (True, 2)
        entry = IdRegistry.objects.get()
        assert entry.full_name == "HYPERLINK(1)"
        assert entry.student_profile.section == "x"

    def test_a_negative_number_in_a_number_column_is_kept_and_rejected(self, world, admin):
        text = (
            "department,code,title,credit,program,level_term\n"
            "CSE,CSE101,Intro,-3,BSC,Level 1 Term 1\n"
        )
        result = run("courses", text, admin)
        assert [(e.column, e.line) for e in result.errors] == [("credit", 2)]
        assert result.sanitized == 0

    @pytest.mark.parametrize(
        "header",
        [
            "student_id,department,program",
            STUDENT_HEADER + ",surprise",
            STUDENT_HEADER + ",student_id",
            "",
        ],
    )
    def test_strict_header(self, world, admin, header):
        with pytest.raises(importers.ImportRejected):
            run("students", header + "\n2101001,CSE,BSC,Level 1 Term 1\n", admin)

    def test_header_is_case_and_order_insensitive(self, world, admin):
        text = "Level_Term,PROGRAM,Department,Student_ID\nLevel 1 Term 1,BSC,CSE,2101001\n"
        assert run("students", text, admin).ok

    def test_row_limit(self, world, admin):
        text = student_rows(*["x,x,x,x,,,"] * (importers.MAX_ROWS + 1))
        with pytest.raises(importers.ImportRejected, match="more than"):
            run("students", text, admin)

    def test_only_the_first_200_errors_are_listed(self, world, admin):
        result = run("students", student_rows(*["!,CSE,BSC,Level 1 Term 1,,,"] * 250), admin)
        assert (len(result.errors), result.error_count) == (200, 250)

    def test_dry_run_saves_nothing_and_issues_no_codes(self, world, admin):
        text = student_rows("2101001,CSE,BSC,Level 1 Term 1,,,")
        result = run("students", text, admin, apply=False, issue_codes=True)
        assert (result.ok, result.created, result.applied, result.issued) == (True, 1, False, [])
        assert IdRegistry.objects.count() == 0
        assert run("students", text, admin).created == 1

    def test_a_failure_while_writing_leaves_nothing_behind(self, world, admin, monkeypatch):
        def boom(*args, **kwargs):
            raise IntegrityError

        monkeypatch.setattr(StudentProfile.objects, "bulk_create", boom)
        with pytest.raises(importers.ImportRejected, match="Nothing was saved"):
            run("students", student_rows("2101001,CSE,BSC,Level 1 Term 1,,,"), admin)
        assert IdRegistry.objects.count() == 0

    def test_activation_codes_are_returned_once_and_only_hashed_in_the_database(self, world, admin):
        text = student_rows(
            "2101001,CSE,BSC,Level 1 Term 1,,,", "2101002,CSE,BSC,Level 1 Term 1,,,"
        )
        result = run("students", text, admin, issue_codes=True, valid_days=7)
        assert len(result.issued) == len({item.code for item in result.issued}) == 2
        for item in result.issued:
            stored = IdRegistry.objects.get(pk=item.registry.pk)
            assert stored.activation_code_hash
            assert item.code not in stored.activation_code_hash
            assert stored.activation_state == "active"

    def test_5k_rows_use_a_constant_number_of_queries(
        self, world, admin, django_assert_max_num_queries
    ):
        text = student_rows(*(f"21{n:06d},CSE,BSC,Level 1 Term 1,,," for n in range(5000)))
        with django_assert_max_num_queries(200):
            result = run("students", text, admin)
        assert result.created == 5000
        assert StudentProfile.objects.count() == 5000

    def test_audit_has_counts_only(self, world, admin):
        run("students", student_rows("2101001,CSE,BSC,Level 1 Term 1,Rahim Uddin,,"), admin)
        event = AuditEvent.objects.get(action="import.applied")
        assert event.metadata == {
            "kind": "students",
            "rows": 1,
            "created": 1,
            "errors": 0,
            "sanitized_cells": 0,
            "codes_issued": 0,
        }
        assert "2101001" not in str(event.metadata) + event.object_id

    def test_rejected_apply_is_audited(self, world, admin):
        run("students", student_rows("!,CSE,BSC,Level 1 Term 1,,,"), admin)
        assert AuditEvent.objects.get(action="import.rejected").metadata["errors"] == 1


class TestOtherImports:
    def test_teachers(self, world, admin):
        text = (
            "teacher_id,department,full_name,designation\nT100,CSE,Karim Sir,Lecturer\nT101,CSE,,\n"
        )
        assert run("teachers", text, admin, issue_codes=True).created == 2
        teacher = TeacherProfile.objects.get(registry__external_id_index=registry_index("T100"))
        assert (teacher.designation, teacher.registry.id_type) == ("Lecturer", IdType.TEACHER)
        assert run("teachers", text, admin).error_count == 2

    def test_courses(self, world, admin):
        text = (
            "department,code,title,credit,program,level_term,type,elective\n"
            "CSE,CSE101,Intro,3,BSC,Level 1 Term 1,,\n"
            "CSE,CSE102,Intro Lab,1.5,BSC,Level 1 Term 1,Lab,yes\n"
        )
        assert run("courses", text, admin).created == 2
        lab = Course.objects.get(code="CSE102")
        assert (lab.course_type, lab.is_elective, str(lab.credit)) == ("lab", True, "1.5")
        assert Course.objects.get(code="CSE101").course_type == "theory"

    @pytest.mark.parametrize(
        ("row", "column"),
        [
            ("CSE,CSE101,Intro,3,BSC,Level 1 Term 1,,", "code"),
            ("CSE,CSE201,Intro,abc,BSC,Level 1 Term 1,,", "credit"),
            ("CSE,CSE201,Intro,0,BSC,Level 1 Term 1,,", "credit"),
            ("CSE,CSE201,Intro,2.55,BSC,Level 1 Term 1,,", "credit"),
            ("CSE,CSE201,Intro,3,BSC,Level 1 Term 1,seminar,", "type"),
            ("CSE,CSE201,Intro,3,BSC,Level 1 Term 1,,maybe", "elective"),
            ("CSE,CSE201,,3,BSC,Level 1 Term 1,,", "title"),
        ],
    )
    def test_course_row_errors(self, world, admin, row, column):
        make_course(world[0], "CSE101")
        text = "department,code,title,credit,program,level_term,type,elective\n" + row + "\n"
        result = run("courses", text, admin)
        assert [e.column for e in result.errors] == [column]
        assert Course.objects.count() == 1

    def test_offerings(self, world, admin):
        department, _, _, semester = world
        course = make_course(department, "CSE101")
        make_teacher(department, external_id="T100")
        header = "department,course_code,semester,teacher_id,section\n"
        assert run("offerings", header + "CSE,cse101,Summer 2026,t100,A\n", admin).created == 1
        offering = CourseOffering.objects.get()
        assert (offering.course, offering.semester, offering.section) == (course, semester, "A")
        again = run(
            "offerings", header + "CSE,CSE101,Summer 2026,T100,A\nCSE,CSE101,Nope,T100,\n", admin
        )
        assert [e.column for e in again.errors] == ["section", "semester"]
        unknown = run("offerings", header + "CSE,CSE101,Summer 2026,T999,B\n", admin)
        assert [e.column for e in unknown.errors] == ["teacher_id"]

    def test_enrollments(self, world, admin):
        department, program, level_term, semester = world
        student = student_in(program, level_term, external_id="2101001")
        offering = make_offering(make_course(department, "CSE101"), semester, section="A")
        header = "student_id,department,course_code,semester,section,status\n"
        result = run("enrollments", header + "2101001,CSE,CSE101,Summer 2026,A,retake\n", admin)
        assert result.created == 1
        enrollment = Enrollment.objects.get()
        assert (enrollment.student_profile, enrollment.offering) == (student, offering)
        assert enrollment.status == EnrollmentStatus.RETAKE

    def test_enrollment_duplicates_unknowns_and_atomicity(self, world, admin):
        department, program, level_term, semester = world
        student_in(program, level_term, external_id="2101001")
        student_in(program, level_term, external_id="2101002")
        student_in(program, level_term, external_id="2101003")
        offering = make_offering(make_course(department, "CSE101"), semester, section="A")
        header = "student_id,department,course_code,semester,section,status\n"
        run("enrollments", header + "2101001,CSE,CSE101,Summer 2026,A,\n", admin)
        text = header + "\n".join(
            [
                "2101002,CSE,CSE101,Summer 2026,A,",
                "2101002,CSE,CSE101,Summer 2026,A,",
                "2101001,CSE,CSE101,Summer 2026,A,",
                "9999999,CSE,CSE101,Summer 2026,A,",
                "2101002,CSE,CSE101,Summer 2026,B,",
                "2101003,CSE,CSE101,Summer 2026,A,audit",
            ]
        )
        result = run("enrollments", text + "\n", admin)
        assert [(e.line, e.column) for e in result.errors] == [
            (3, "student_id"),
            (4, "student_id"),
            (5, "student_id"),
            (6, "course_code"),
            (7, "status"),
        ]
        assert list(Enrollment.objects.values_list("offering", flat=True)) == [offering.pk]

    def test_templates_round_trip_through_the_importer(self, world, admin):
        for key, importer in importers.IMPORTERS.items():
            buffer = io.StringIO()
            csv.writer(buffer).writerows(importers.template_rows(importer))
            rows = list(csv.reader(io.StringIO(buffer.getvalue())))
            assert {len(row) for row in rows} == {len(importer.required + importer.optional)}, key
            assert importers._check_header(importer(), rows[0]) == list(importer().columns)


class TestImportScreens:
    def upload(self, client, kind, text, **extra):
        body = SimpleUploadedFile("data.csv", text.encode("utf-8-sig"), content_type="text/csv")
        return client.post(reverse("academics:import_upload", args=[kind]), {"file": body, **extra})

    def test_only_admins(self, client, world):
        urls = [
            reverse("academics:import_index"),
            reverse("academics:import_upload", args=["students"]),
            reverse("academics:import_template", args=["students"]),
            reverse("academics:assign_teachers"),
            reverse("enrollment:group"),
            reverse("enrollment:list"),
            reverse("enrollment:missing"),
        ]
        assert all(client.get(url).status_code == 302 for url in urls)
        sign_in(client, make_hod())
        assert all(client.get(url).status_code == 403 for url in urls)

    def test_unknown_kind_is_404(self, admin_client):
        assert (
            admin_client.get(reverse("academics:import_upload", args=["nope"])).status_code == 404
        )

    def test_index_and_template_download(self, admin_client):
        assert admin_client.get(reverse("academics:import_index")).status_code == 200
        response = admin_client.get(reverse("academics:import_template", args=["students"]))
        assert response["Content-Type"].startswith("text/csv")
        assert response.content.startswith("﻿".encode())
        assert response.content.decode("utf-8-sig").splitlines()[0] == STUDENT_HEADER

    def test_preview_then_apply(self, admin_client, world):
        response = self.upload(
            admin_client, "students", student_rows("2101001,CSE,BSC,Level 1 Term 1,,,")
        )
        assert response.status_code == 200
        assert IdRegistry.objects.count() == 0
        token = re.search(r'name="token" value="([^"]+)"', response.content.decode()).group(1)
        applied = admin_client.post(
            reverse("academics:import_apply", args=["students"]), {"token": token}
        )
        assert applied.status_code == 302
        assert IdRegistry.objects.count() == 1
        replay = admin_client.post(
            reverse("academics:import_apply", args=["students"]), {"token": token}
        )
        assert replay.status_code == 302
        assert IdRegistry.objects.count() == 1

    def test_preview_shows_row_errors_and_offers_no_confirmation(self, admin_client, world):
        response = self.upload(
            admin_client, "students", student_rows("!!,CSE,BSC,Level 1 Term 1,,,")
        )
        page = response.content.decode()
        assert "1 rows have errors" in page
        assert 'name="token"' not in page

    def test_bad_file_is_a_form_error(self, admin_client):
        body = SimpleUploadedFile("data.csv", b"a,b\n1,2\n", content_type="text/csv")
        response = admin_client.post(
            reverse("academics:import_upload", args=["students"]), {"file": body}
        )
        assert response.status_code == 200
        assert "header row does not match" in response.content.decode()

    def test_apply_with_codes_downloads_the_codes_once(self, admin_client, world):
        response = self.upload(
            admin_client,
            "students",
            student_rows("2101001,CSE,BSC,Level 1 Term 1,,,"),
            issue_codes="on",
            valid_days="7",
        )
        token = re.search(r'name="token" value="([^"]+)"', response.content.decode()).group(1)
        applied = admin_client.post(
            reverse("academics:import_apply", args=["students"]), {"token": token}
        )
        assert applied["Content-Type"].startswith("text/csv")
        rows = list(csv.reader(io.StringIO(applied.content.decode("utf-8-sig"))))
        assert len(rows) == 2
        assert re.fullmatch(r"[A-Z2-9]{4}(-[A-Z2-9]{4}){2}", rows[1][3])

    def test_a_token_only_works_for_its_owner_and_kind(self, admin_client, admin, world):
        token = staging.stash(
            make_admin(), "students", student_rows("2101001,CSE,BSC,Level 1 Term 1,,,"), {}
        )
        assert staging.take(admin, "students", token) is None
        mine = staging.stash(admin, "students", "x", {})
        assert staging.take(admin, "teachers", mine) is None
        admin_client.post(reverse("academics:import_apply", args=["students"]), {"token": "bogus"})
        assert IdRegistry.objects.count() == 0


class TestAssignTeachers:
    def test_grid_lists_offerings_and_saves_changes(self, admin_client, admin, world):
        department, _, _, semester = world
        offering = make_offering(make_course(department, "CSE101"), semester)
        other = make_teacher(department)
        page = admin_client.get(reverse("academics:assign_teachers"))
        assert page.status_code == 200
        assert f'name="teacher_{offering.pk}"' in page.content.decode()
        response = admin_client.post(
            reverse("academics:assign_teachers"), {f"teacher_{offering.pk}": str(other.pk)}
        )
        assert response.status_code == 302
        offering.refresh_from_db()
        assert offering.teacher == other
        assert AuditEvent.objects.get(action="academics.teachers_assigned").metadata == {
            "offerings": 1
        }

    def test_unknown_teacher_changes_nothing(self, admin, world):
        offering = make_offering(make_course(world[0], "CSE101"), world[3])
        before = offering.teacher_id
        other = make_offering(make_course(world[0], "CSE102"), world[3])
        with pytest.raises(Exception, match="no longer exist"):
            assignments.assign_teachers({offering.pk: other.teacher_id, other.pk: 0}, actor=admin)
        offering.refresh_from_db()
        assert offering.teacher_id == before

    def test_filters_by_department(self, admin_client, world):
        department, _, _, semester = world
        mine = make_offering(make_course(department, "CSE101"), semester)
        elsewhere = make_offering(make_course(DepartmentFactory(), "EEE101"), semester)
        page = admin_client.get(
            reverse("academics:assign_teachers"), {"department": department.pk}
        ).content.decode()
        assert f"teacher_{mine.pk}" in page
        assert f"teacher_{elsewhere.pk}" not in page


class TestGroupEnrollment:
    def setup_group(self, world):
        department, program, level_term, semester = world
        students = [
            student_in(program, level_term, "A"),
            student_in(program, level_term, "B"),
            student_in(program, level_term, ""),
        ]
        shared = make_offering(
            make_course(department, "CSE101", level_term=level_term, program=program),
            semester,
            section="",
        )
        section_a = make_offering(
            make_course(department, "CSE102", level_term=level_term, program=program),
            semester,
            section="A",
        )
        return students, shared, section_a

    def test_enrolls_active_students_of_the_group_in_matching_offerings(self, world, admin):
        department, program, level_term, semester = world
        students, shared, section_a = self.setup_group(world)
        make_offering(
            make_course(
                department, "CSE103", level_term=level_term, program=program, is_elective=True
            ),
            semester,
        )
        make_offering(make_course(department, "CSE201", program=program), semester)
        make_offering(
            make_course(department, "CSE104", level_term=level_term, program=program),
            make_semester(),
        )
        other_program = student_in(ProgramFactory(department=department), level_term)
        dropped = student_in(program, level_term)
        dropped.academic_status = "dropped"
        dropped.save()

        plan = enrollments.enroll_group(program, level_term, actor=admin)
        assert (plan.students, plan.offerings, len(plan.new)) == (3, 2, 4)
        pairs = set(Enrollment.objects.values_list("student_profile_id", "offering_id"))
        assert pairs == {
            (students[0].pk, shared.pk),
            (students[1].pk, shared.pk),
            (students[2].pk, shared.pk),
            (students[0].pk, section_a.pk),
        }
        assert not Enrollment.objects.filter(student_profile__in=[other_program, dropped]).exists()
        assert all(e.status == EnrollmentStatus.REGULAR for e in Enrollment.objects.all())

    def test_running_again_creates_nothing(self, world, admin):
        self.setup_group(world)
        enrollments.enroll_group(world[1], world[2], actor=admin)
        again = enrollments.enroll_group(world[1], world[2], actor=admin)
        assert again.new == []
        assert Enrollment.objects.count() == 4

    def test_audit_counts_only(self, world, admin):
        self.setup_group(world)
        enrollments.enroll_group(world[1], world[2], actor=admin)
        metadata = AuditEvent.objects.get(action="enrollment.group_enrolled").metadata
        assert (metadata["students"], metadata["offerings"], metadata["created"]) == (3, 2, 4)

    def test_without_a_current_semester(self, admin_client):
        Semester.objects.update(start_date=date(2020, 1, 1), end_date=date(2020, 6, 30))
        program, level_term = ProgramFactory(), LevelTermFactory()
        page = admin_client.get(
            reverse("enrollment:group"), {"program": program.pk, "level_term": level_term.pk}
        )
        assert "no current semester" in page.content.decode()

    def test_screen_previews_then_enrolls(self, admin_client, world):
        self.setup_group(world)
        params = {"program": world[1].pk, "level_term": world[2].pk}
        preview = admin_client.get(reverse("enrollment:group"), params)
        assert "4 new enrollments" in preview.content.decode()
        assert Enrollment.objects.count() == 0
        assert admin_client.post(reverse("enrollment:group"), params).status_code == 302
        assert Enrollment.objects.count() == 4


class TestSingleEnrollment:
    def test_enroll_remove_and_duplicate(self, admin_client, world):
        department, program, level_term, semester = world
        student = student_in(program, level_term, external_id="2101001")
        offering = make_offering(make_course(department, "CSE101"), semester)
        data = {"student_id": "2101001", "offering": offering.pk, "status": "retake"}
        assert admin_client.post(reverse("enrollment:list"), data).status_code == 302
        enrollment = Enrollment.objects.get()
        assert (enrollment.student_profile, enrollment.status) == (student, "retake")
        duplicate = admin_client.post(reverse("enrollment:list"), data)
        assert "already enrolled" in duplicate.content.decode()
        listing = admin_client.get(reverse("enrollment:list")).content.decode()
        assert "2101001" in listing
        url = reverse("enrollment:remove", args=[enrollment.pk])
        assert admin_client.get(url).status_code == 200
        assert admin_client.post(url).status_code == 302
        assert not Enrollment.objects.exists()
        assert AuditEvent.objects.filter(action="enrollment.removed").count() == 1

    def test_unknown_student_and_past_semester_offering_are_rejected(self, admin_client, world):
        department, program, level_term, _ = world
        student_in(program, level_term, external_id="2101001")
        past = make_offering(make_course(department, "CSE101"), make_semester())
        unknown = admin_client.post(
            reverse("enrollment:list"),
            {"student_id": "999", "offering": past.pk, "status": "regular"},
        )
        page = unknown.content.decode()
        assert "No registered student has this ID" in page
        assert "Select a valid choice" in page
        assert not Enrollment.objects.exists()

    def test_the_list_can_be_searched_by_student_id(self, admin_client, world):
        department, program, level_term, semester = world
        offering = make_offering(make_course(department, "CSE101"), semester)
        for external_id in ("2101001", "2101002"):
            Enrollment.objects.create(
                student_profile=student_in(program, level_term, external_id=external_id),
                offering=offering,
            )
        page = admin_client.get(
            reverse("enrollment:list"), {"student_id": "2101002"}
        ).content.decode()
        assert "2101002" in page
        assert "2101001" not in page


class TestMissingEnrollment:
    def test_lists_active_students_without_a_current_enrollment(self, admin_client, world):
        department, program, level_term, semester = world
        enrolled = student_in(program, level_term, external_id="2101001")
        missing = student_in(program, level_term, external_id="2101002")
        past_only = student_in(program, level_term, external_id="2101003")
        dropped = student_in(program, level_term, external_id="2101004")
        dropped.academic_status = "dropped"
        dropped.save()
        Enrollment.objects.create(
            student_profile=enrolled,
            offering=make_offering(make_course(department, "A1"), semester),
        )
        Enrollment.objects.create(
            student_profile=past_only,
            offering=make_offering(make_course(department, "A2"), make_semester()),
        )
        assert set(students_missing_enrollment()) == {missing, past_only}
        page = admin_client.get(reverse("enrollment:missing")).content.decode()
        assert "2101002" in page
        assert "2101003" in page
        assert "2101001" not in page
        assert "2101004" not in page

    def test_filters(self, admin_client, world):
        _, program, level_term, _ = world
        student_in(program, level_term, external_id="2101001")
        other = student_in(ProgramFactory(), LevelTermFactory(), external_id="2101002")
        page = admin_client.get(
            reverse("enrollment:missing"), {"department": other.program.department_id}
        ).content.decode()
        assert "2101002" in page
        assert "2101001" not in page


class TestLevelTermCell:
    def test_term_is_accepted_as_a_number_or_a_roman_numeral(self, world, admin):
        _, program, _, _ = world
        second = LevelTermFactory(level=1, term=2)
        result = run(
            "students",
            student_rows(
                "2101001,CSE,BSC,Level 1 Term 2,,,",
                "2101002,CSE,BSC,level 1 term ii,,,",
                "2101003,CSE,BSC,LEVEL 1 TERM I,,,",
            ),
            admin,
        )
        assert (result.ok, result.created) == (True, 3)
        profiles = StudentProfile.objects.filter(program=program)
        assert profiles.filter(level_term=second).count() == 2

    @pytest.mark.parametrize(
        "cell", ["Level 1 Term III", "Level 1 Term", "Level 1 Term 0", "Term II"]
    )
    def test_other_cells_are_unknown(self, world, admin, cell):
        result = run("students", student_rows(f"2101001,CSE,BSC,{cell},,,"), admin)
        assert result.ok is False


@pytest.mark.parametrize("kind", [None, *importers.IMPORTERS])
def test_import_pages_never_build_an_importer(admin_client, monkeypatch, kind):
    """An importer loads whole tables when built; showing a page must not build one."""

    def refuse(self, **options):
        raise AssertionError("an import page built an importer")

    monkeypatch.setattr(importers.Importer, "__init__", refuse)
    if kind:
        url, shown = reverse("academics:import_upload", args=[kind]), [kind]
    else:
        url, shown = reverse("academics:import_index"), list(importers.IMPORTERS)

    response = admin_client.get(url)

    assert response.status_code == 200
    html = response.content.decode()
    assert all(str(importers.IMPORTERS[key].title) in html for key in shown)
