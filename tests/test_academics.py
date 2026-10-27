from datetime import date, timedelta

import pytest
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.academics.models import (
    Course,
    CourseOffering,
    Department,
    GradeScale,
    Season,
    Semester,
)
from apps.academics.screens import SCREENS
from apps.academics.selectors import get_current_courses
from apps.academics.services import semesters
from apps.auditlog.models import AuditEvent
from apps.enrollment.models import Enrollment
from tests.factories import (
    BatchFactory,
    DepartmentFactory,
    LevelTermFactory,
    ProgramFactory,
    claim,
    make_admin,
    make_hod,
    make_student,
    make_teacher,
    sign_in,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(client):
    client.defaults["HTTP_ACCEPT_LANGUAGE"] = "en"
    sign_in(client, make_admin())
    return client


def free_season_year() -> tuple[str, int]:
    taken = set(Semester.objects.values_list("season", "year"))
    keys = ((season, year) for year in range(2000, 2101) for season in Season.values)
    return next(key for key in keys if key not in taken)


def make_semester(current=False, **fields):
    """A semester with an unused season and year. ``current`` makes it run today; otherwise it
    ran in the first half of 2026, unless dates are given."""
    today = semesters.today()
    start, end = (
        (today - timedelta(days=30), today + timedelta(days=120))
        if current
        else (date(2026, 1, 1), date(2026, 6, 30))
    )
    season, year = free_season_year()
    return Semester.objects.create(
        season=fields.pop("season", season),
        year=fields.pop("year", year),
        start_date=fields.pop("start_date", start),
        end_date=fields.pop("end_date", end),
        **fields,
    )


def make_course(department=None, code="CSE101", level_term=None, **fields):
    department = department or DepartmentFactory()
    return Course.objects.create(
        code=code,
        title=fields.pop("title", "Programming"),
        credit=fields.pop("credit", 3),
        department=department,
        program=fields.pop("program", None) or ProgramFactory(department=department),
        level_term=level_term or LevelTermFactory(),
        **fields,
    )


def make_offering(course=None, semester=None, teacher=None, section="A"):
    course = course or make_course()
    return CourseOffering.objects.create(
        course=course,
        semester=semester or make_semester(),
        teacher=teacher or make_teacher(course.department),
        section=section,
    )


def all_urls(screen, obj):
    return [
        reverse("academics:list", args=[screen.key]),
        reverse("academics:create", args=[screen.key]),
        reverse("academics:edit", args=[screen.key, obj.pk]),
        reverse("academics:delete", args=[screen.key, obj.pk]),
    ]


def screen_url_accepts_post(url):
    """Every screen URL takes POST except the read-only list pages."""
    return not url.endswith(tuple(f"/{key}/" for key in SCREENS))


def sample_objects():
    offering = make_offering()
    course = offering.course
    return {
        "departments": course.department,
        "programs": course.program,
        "batches": BatchFactory(program=course.program),
        "level-terms": course.level_term,
        "semesters": offering.semester,
        "courses": course,
        "offerings": offering,
        "grades": GradeScale.objects.create(
            letter=f"G{GradeScale.objects.count()}", points="1.00", is_pass=True
        ),
    }


class TestModels:
    def test_one_semester_per_season_and_year(self):
        make_semester(season=Season.SUMMER, year=2026)
        with pytest.raises(IntegrityError), transaction.atomic():
            make_semester(season=Season.SUMMER, year=2026, start_date=date(2027, 7, 1))

    def test_semester_must_end_after_it_starts(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            make_semester(start_date=date(2026, 6, 1), end_date=date(2026, 1, 1))

    def test_offering_unique_per_course_semester_section(self):
        offering = make_offering()
        with pytest.raises(IntegrityError), transaction.atomic():
            CourseOffering.objects.create(
                course=offering.course,
                semester=offering.semester,
                teacher=offering.teacher,
                section="A",
            )

    def test_offering_department_is_the_courses(self):
        offering = make_offering()
        assert offering.department == offering.course.department


class TestPermissions:
    def test_non_admins_get_403_everywhere(self, client):
        objects = sample_objects()
        users = [
            claim(make_student()),
            claim(make_teacher()),
            make_hod(),
        ]
        for user in users:
            sign_in(client, user)
            for key, obj in objects.items():
                for url in all_urls(SCREENS[key], obj):
                    assert client.get(url).status_code == 403, url
                    if screen_url_accepts_post(url):
                        assert client.post(url).status_code == 403, url

    def test_anonymous_is_sent_to_login(self, client):
        response = client.get(reverse("academics:list", args=["courses"]))
        assert response.status_code == 302

    def test_unknown_entity_is_404(self, admin_client):
        assert admin_client.get(reverse("academics:list", args=["nope"])).status_code == 404


class TestScreens:
    def test_every_list_edit_and_delete_page_renders(self, admin_client):
        for key, obj in sample_objects().items():
            screen = SCREENS[key]
            for url in [
                reverse("academics:list", args=[key]),
                reverse("academics:create", args=[key]),
                reverse("academics:edit", args=[key, obj.pk]),
                reverse("academics:delete", args=[key, obj.pk]),
            ]:
                assert admin_client.get(url).status_code == 200, (screen.key, url)

    def test_sidebar_lists_every_screen(self, admin_client):
        body = admin_client.get(reverse("academics:list", args=["courses"])).content.decode()
        for screen in SCREENS.values():
            assert reverse("academics:list", args=[screen.key]) in body

    def test_admin_builds_the_whole_structure(self, admin_client):
        def create(key, data):
            response = admin_client.post(reverse("academics:create", args=[key]), data)
            assert response.status_code == 302, response.content.decode()

        create("departments", {"code": "CSE", "name": "Computer Science", "is_active": "on"})
        department = Department.objects.get(code="CSE")
        create("programs", {"department": department.pk, "code": "BSC", "name": "B.Sc."})
        program = department.programs.get()
        create("batches", {"program": program.pk, "name": "2026"})
        create("level-terms", {"level": 1, "term": 1, "order": 1})
        level_term = LevelTermFactory._meta.model.objects.get(order=1)
        create(
            "semesters",
            {
                "season": "winter",
                "year": "2026",
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
            },
        )
        create(
            "courses",
            {
                "code": "CSE101",
                "title": "Programming",
                "credit": "3.0",
                "course_type": "theory",
                "department": department.pk,
                "program": program.pk,
                "level_term": level_term.pk,
            },
        )
        teacher = make_teacher(department)
        create(
            "offerings",
            {
                "course": Course.objects.get().pk,
                "semester": Semester.objects.get().pk,
                "teacher": teacher.pk,
                "section": "A",
            },
        )
        assert CourseOffering.objects.count() == 1

    def test_course_program_must_belong_to_its_department(self, admin_client):
        course = make_course()
        other_program = ProgramFactory()
        response = admin_client.post(
            reverse("academics:edit", args=["courses", course.pk]),
            {
                "code": course.code,
                "title": course.title,
                "credit": "3.0",
                "course_type": "theory",
                "department": course.department_id,
                "program": other_program.pk,
                "level_term": course.level_term_id,
            },
        )
        assert response.status_code == 200
        assert "must belong to the course" in response.content.decode()

    def test_duplicate_code_shows_a_friendly_error(self, admin_client):
        course = make_course()
        response = admin_client.post(
            reverse("academics:create", args=["courses"]),
            {
                "code": course.code,
                "title": "Other",
                "credit": "3.0",
                "course_type": "theory",
                "department": course.department_id,
                "program": course.program_id,
                "level_term": course.level_term_id,
            },
        )
        assert response.status_code == 200
        assert "already has a course with this code" in response.content.decode()

    def test_list_filters_and_search(self, admin_client):
        make_course(code="CSE101", title="Programming")
        make_course(code="EEE201", title="Circuits")
        url = reverse("academics:list", args=["courses"])
        body = admin_client.get(url, {"q": "circ"}).content.decode()
        assert "EEE201" in body and "CSE101" not in body
        elective = make_course(code="CSE300", is_elective=True)
        body = admin_client.get(url, {"elective": "1"}).content.decode()
        assert elective.code in body and "EEE201" not in body

    def test_lists_paginate(self, admin_client):
        DepartmentFactory.create_batch(55)
        response = admin_client.get(reverse("academics:list", args=["departments"]))
        assert response.context["page_obj"].paginator.num_pages == 2


class TestServiceCourses:
    def post_offering(self, client, offering, teacher, **extra):
        return client.post(
            reverse("academics:edit", args=["offerings", offering.pk]),
            {
                "course": offering.course_id,
                "semester": offering.semester_id,
                "teacher": teacher.pk,
                "section": offering.section,
                **extra,
            },
        )

    def test_other_department_teacher_needs_confirmation(self, admin_client):
        offering = make_offering()
        outsider = make_teacher()
        response = self.post_offering(admin_client, offering, outsider)
        assert response.status_code == 200
        assert "Tick the box to confirm a service course" in response.content.decode()
        offering.refresh_from_db()
        assert offering.teacher_id != outsider.pk

    def test_confirmed_service_course_is_saved(self, admin_client):
        offering = make_offering()
        outsider = make_teacher()
        response = self.post_offering(admin_client, offering, outsider, confirm_service_course="on")
        assert response.status_code == 302
        offering.refresh_from_db()
        assert offering.teacher_id == outsider.pk

    def test_same_department_teacher_needs_no_confirmation(self, admin_client):
        offering = make_offering()
        colleague = make_teacher(offering.course.department)
        assert self.post_offering(admin_client, offering, colleague).status_code == 302


class TestDelete:
    def test_unused_record_is_deleted(self, admin_client):
        department = DepartmentFactory()
        response = admin_client.post(
            reverse("academics:delete", args=["departments", department.pk])
        )
        assert response.status_code == 302
        assert not Department.objects.filter(pk=department.pk).exists()

    def test_used_record_is_kept_with_a_friendly_message(self, admin_client):
        offering = make_offering()
        url = reverse("academics:delete", args=["courses", offering.course_id])
        response = admin_client.post(url, follow=True)
        assert Course.objects.filter(pk=offering.course_id).exists()
        text = response.content.decode()
        assert "cannot be deleted" in text and "1 course offerings" in text
        assert not AuditEvent.objects.filter(action="academics.deleted").exists()


class TestAudit:
    def test_create_update_delete_are_audited(self, admin_client):
        admin_client.post(
            reverse("academics:create", args=["departments"]), {"code": "EEE", "name": "Electrical"}
        )
        department = Department.objects.get(code="EEE")
        admin_client.post(
            reverse("academics:edit", args=["departments", department.pk]),
            {"code": "EEE", "name": "Electrical Engineering"},
        )
        admin_client.post(reverse("academics:delete", args=["departments", department.pk]))
        events = list(AuditEvent.objects.filter(action__startswith="academics.").order_by("id"))
        assert [e.action for e in events] == [
            "academics.created",
            "academics.updated",
            "academics.deleted",
        ]
        assert events[1].metadata == {"entity": "departments", "changed": ["name"]}
        assert {e.department_id for e in events} == {department.pk}

    def test_unchanged_save_writes_no_audit_row(self, admin_client):
        department = DepartmentFactory()
        admin_client.post(
            reverse("academics:edit", args=["departments", department.pk]),
            {"code": department.code, "name": department.name, "is_active": "on"},
        )
        assert not AuditEvent.objects.filter(action="academics.updated").exists()


class TestQueryCounts:
    @pytest.mark.parametrize("key", list(SCREENS))
    def test_list_queries_do_not_grow_with_rows(self, admin_client, key):
        url = reverse("academics:list", args=[key])

        def count():
            with CaptureQueriesContext(connection) as queries:
                assert admin_client.get(url).status_code == 200
            return len(queries)

        sample_objects()
        few = count()
        for _ in range(4):
            sample_objects()
        assert count() == few


class TestCurrentCourses:
    def test_returns_only_enrolled_offerings_of_the_current_semester(self):
        student = make_student()
        department = student.program.department
        current, past = make_semester(current=True), make_semester()
        course = make_course(department, "CSE101", level_term=student.level_term)
        wanted = make_offering(course, current)
        old = make_offering(course, past)
        not_enrolled = make_offering(make_course(department, "CSE201"), current)
        for offering in (wanted, old):
            Enrollment.objects.create(student_profile=student, offering=offering)
        Enrollment.objects.create(student_profile=make_student(), offering=not_enrolled)
        assert get_current_courses(student) == [wanted]

    def test_curriculum_alone_does_not_enroll(self):
        student = make_student()
        current = make_semester(current=True)
        make_offering(
            make_course(student.program.department, level_term=student.level_term), current
        )
        assert get_current_courses(student) == []

    def test_no_current_semester_means_no_courses(self):
        student = make_student()
        offering = make_offering(make_course(student.program.department))
        Enrollment.objects.create(student_profile=student, offering=offering)
        assert get_current_courses(student) == []

    def test_query_count_is_constant(self, django_assert_num_queries):
        student = make_student()
        department = student.program.department
        current = make_semester(current=True)
        for n in range(3):
            offering = make_offering(make_course(department, f"C{n}"), current)
            Enrollment.objects.create(student_profile=student, offering=offering)
        with django_assert_num_queries(1):
            titles = [
                (offering.course.title, offering.teacher.registry.full_name)
                for offering in get_current_courses(student)
            ]
        assert len(titles) == 3
