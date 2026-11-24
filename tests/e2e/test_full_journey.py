"""The whole story, end to end, through the real admin pages, sign-up, login and dashboards.

The Admin builds the term through the same pages and forms a person would use; students and
teachers sign up with their ID and activation code and log in with a password. Only the
question bank is created directly (it is not what these tests are about).
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import Course, CourseOffering, Department, LevelTerm, Program, Semester
from apps.academics.services import semesters
from apps.academics.services.teaching import offerings_for_teacher
from apps.accounts.models import (
    IdRegistry,
    IdType,
    StudentProfile,
    TeacherProfile,
    registry_index,
)
from apps.enrollment.models import Enrollment, EnrollmentStatus
from apps.enrollment.services.courses import courses_for_student
from apps.feedback.models import FeedbackResponse, FeedbackWindow, QuestionType, SubmissionReceipt
from apps.feedback.services import portal
from tests.factories import PASSWORD, make_admin, sign_in
from tests.test_feedback_core import make_question

pytestmark = pytest.mark.django_db

DATETIME = "%Y-%m-%dT%H:%M"


def english_client() -> Client:
    client = Client()
    client.defaults["HTTP_ACCEPT_LANGUAGE"] = "en"
    return client


def local(day: date, hour: int = 0, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=timezone.get_default_timezone())


def stamp(moment: datetime) -> str:
    return timezone.localtime(moment, timezone.get_default_timezone()).strftime(DATETIME)


@dataclass
class Office:
    """The Admin at work: every step is a POST to the page the Admin would use."""

    web: Client
    codes: dict[str, str] = field(default_factory=dict)

    def post(self, name, data, *args, expect=302):
        response = self.web.post(reverse(name, args=args), data)
        assert response.status_code == expect, (
            name,
            getattr(response, "context", None) and _errors(response),
        )
        return response

    def create(self, entity, **data):
        self.post("academics:create", data, entity)

    def department(self, code) -> Department:
        self.create("departments", code=code, name=f"{code} department", name_bn="", is_active="on")
        return Department.objects.get(code=code)

    def program(self, department, code="BSC") -> Program:
        self.create("programs", department=department.pk, code=code, name=f"{code} programme")
        return Program.objects.get(department=department, code=code)

    def level_term(self, level, term, order) -> LevelTerm:
        self.create("level-terms", level=level, term=term, order=order)
        return LevelTerm.objects.get(level=level, term=term)

    def semester(self, season, year, start, end) -> Semester:
        self.create(
            "semesters",
            season=season,
            year=year,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )
        return Semester.objects.get(season=season, year=year)

    def course(self, department, program, level_term, code, **extra) -> Course:
        self.create(
            "courses",
            code=code,
            title=f"Course {code}",
            title_bn="",
            credit="3.0",
            course_type=extra.get("course_type", "theory"),
            **({"is_elective": "on"} if extra.get("is_elective") else {}),
            department=department.pk,
            program=program.pk,
            level_term=level_term.pk,
        )
        return Course.objects.get(department=department, code=code)

    def offering(self, course, semester, teacher, section="") -> CourseOffering:
        self.create(
            "offerings",
            course=course.pk,
            semester=semester.pk,
            teacher=teacher.pk,
            section=section,
        )
        return CourseOffering.objects.get(course=course, semester=semester, section=section)

    def register_teacher(self, external_id, department, *, role="teacher") -> TeacherProfile:
        data = {
            "external_id": external_id,
            "full_name": f"Teacher {external_id}",
            "department": department.pk,
            "designation": "Lecturer",
            "role": role,
        }
        if role == "hod":
            data["hod_department"] = department.pk
        self.post("accounts:registry_create", data, IdType.TEACHER)
        return TeacherProfile.objects.get(registry__external_id_index=_index(external_id))

    def register_student(self, external_id, department, program, level_term, section=""):
        self.post(
            "accounts:registry_create",
            {
                "external_id": external_id,
                "full_name": f"Student {external_id}",
                "department": department.pk,
                "program": program.pk,
                "batch": "",
                "level_term": level_term.pk,
                "section": section,
                "academic_status": "active",
            },
            IdType.STUDENT,
        )
        return StudentProfile.objects.get(registry__external_id_index=_index(external_id))

    def issue_codes(self, *profiles) -> None:
        """Generate activation codes on the registry page; the CSV is the only place they exist."""
        response = self.web.post(
            reverse("accounts:registry_bulk"),
            {"action": "generate_codes", "valid_days": 7, "ids": [p.registry_id for p in profiles]},
        )
        assert response.status_code == 200
        rows = list(csv.reader(io.StringIO(response.content.decode().lstrip("﻿"))))
        for row in rows[1:]:
            self.codes[row[0]] = row[3]

    def enroll(self, profile, offering, status=EnrollmentStatus.REGULAR, *, expect=302):
        return self.post(
            "enrollment:list",
            {
                "student_id": profile.registry.external_id,
                "offering": offering.pk,
                "status": status,
            },
            expect=expect,
        )

    def enroll_group(self, program, level_term):
        self.post("enrollment:group", {"program": program.pk, "level_term": level_term.pk})

    def open_round(self, semester, name, opens, closes, *, expect=302, **scope):
        data = {
            "semester": semester.pk,
            "name": name,
            "opens_at": stamp(opens),
            "closes_at": stamp(closes),
            "is_active": "on",
            **scope,
        }
        response = self.post("feedback:window_create", data, expect=expect)
        return (
            response if expect != 302 else FeedbackWindow.objects.get(semester=semester, name=name)
        )

    def edit_round(self, window, **changes):
        data = {
            "semester": window.semester_id,
            "name": window.name,
            "opens_at": stamp(window.opens_at),
            "closes_at": stamp(window.closes_at),
            "is_active": "on",
            **changes,
        }
        self.post("feedback:window_edit", data, window.pk)
        window.refresh_from_db()


def _index(external_id):
    return registry_index(external_id)


def _errors(response):
    context = response.context
    form = context.get("form") if context else None
    return form.errors if form is not None else None


def sign_up(office: Office, profile) -> Client:
    """Claim the ID with its activation code, choose a password, then log in afresh."""
    client = english_client()
    external_id = profile.registry.external_id
    claimed = client.post(
        reverse("accounts:signup"),
        {"registry_id": external_id, "activation_code": office.codes[external_id]},
    )
    assert claimed.context["stage"] == "password"
    done = client.post(
        reverse("accounts:signup_password"), {"password1": PASSWORD, "password2": PASSWORD}
    )
    assert done.context["stage"] == "done"
    client.post(reverse("accounts:logout"))
    username = IdRegistry.objects.get(pk=profile.registry_id).claimed_by.username
    login = client.post(reverse("accounts:login"), {"username": username, "password": PASSWORD})
    assert login.status_code == 302
    return client


def give_feedback(client, window, offering):
    questions = portal.form_questions(offering)
    data = {"qset": portal.fingerprint(questions), "password": PASSWORD}
    for question in questions:
        data[f"q{question.pk}"] = "Helpful classes." if question.question_type == "text" else "4"
    return client.post(reverse("feedback:form", args=[window.pk, offering.pk]), data)


def student_cards(client):
    page = client.get(reverse("accounts:dashboard_student"))
    assert page.status_code == 200
    return page, {entry.offering.course.code: entry for entry in page.context["dashboard"].entries}


@pytest.fixture
def bank():
    make_question(QuestionType.RATING, order=1, text="Explains clearly.")
    make_question(QuestionType.TEXT, order=2, required=False, text="Anything else?")


@pytest.fixture
def office(bank):
    web = english_client()
    sign_in(web, make_admin(PASSWORD))
    return Office(web)


@dataclass
class Term:
    office: Office
    cse: Department
    bsc: Program
    first: LevelTerm
    second: LevelTerm
    current: Semester
    previous: Semester
    teacher: TeacherProfile
    courses: dict[str, Course]
    offerings: dict[str, CourseOffering]


@pytest.fixture
def term(office) -> Term:
    today = semesters.today()
    cse = office.department("CSE")
    bsc = office.program(cse)
    first, second = office.level_term(1, 1, 1), office.level_term(1, 2, 2)
    previous = office.semester(
        "winter", today.year - 1, date(today.year - 1, 1, 1), date(today.year - 1, 6, 30)
    )
    current = office.semester(
        "summer",
        today.year - 1 if today.month < 7 else today.year,
        today - timedelta(days=30),
        today + timedelta(days=90),
    )
    teacher = office.register_teacher("T-100", cse)
    courses = {
        # CSE102 is an elective: the level/term rule leaves it to the Admin.
        code: office.course(cse, bsc, level, code, is_elective=code == "CSE102")
        for code, level in (("CSE101", first), ("CSE102", first), ("CSE201", second))
    }
    offerings = {code: office.offering(courses[code], current, teacher) for code in courses}
    offerings["old"] = office.offering(courses["CSE101"], previous, teacher)
    return Term(office, cse, bsc, first, second, current, previous, teacher, courses, offerings)


# --- the journey -----------------------------------------------------------------------------


def test_the_whole_term_works_for_every_role(term, settings):
    office, now = term.office, timezone.now()
    settings.MIN_RESPONSES = 3

    # b. a new student is registered, gets a code, signs up and logs in
    alice = office.register_student("S-001", term.cse, term.bsc, term.first)
    office.issue_codes(alice, term.teacher)
    alice_web = sign_up(office, alice)
    teacher_web = sign_up(office, term.teacher)

    # c. the level/term rule gave her CSE101 when she was registered; the Admin adds the
    # elective, and a second add of the same course is refused. Two more students of the
    # level/term are placed by the same rule; group enrolment then finds nothing left to do.
    office.enroll(alice, term.offerings["CSE102"])
    duplicate = office.enroll(alice, term.offerings["CSE101"], expect=200)
    assert "already enrolled" in duplicate.content.decode()
    bob = office.register_student("S-002", term.cse, term.bsc, term.first)
    carol = office.register_student("S-003", term.cse, term.bsc, term.first)
    office.enroll_group(term.bsc, term.first)
    assert Enrollment.objects.filter(offering=term.offerings["CSE101"]).count() == 3
    office.issue_codes(bob, carol)
    bob_web, carol_web = sign_up(office, bob), sign_up(office, carol)

    # d. a round opens for the semester
    window = office.open_round(
        term.current, "Mid-term", now - timedelta(hours=1), now + timedelta(days=3)
    )

    # e. every dashboard shows it
    page, cards = student_cards(alice_web)
    assert page.context["dashboard"].round.window == window
    assert set(cards) == {"CSE101", "CSE102"}
    assert all(card.can_give for card in cards.values())
    assert (
        reverse("feedback:form", args=[window.pk, term.offerings["CSE101"].pk])
        in page.content.decode()
    )

    teacher_page = teacher_web.get(reverse("accounts:dashboard_teacher"))
    shown = [course.offering for course in teacher_page.context["courses"]]
    assert shown == [term.offerings[code] for code in ("CSE101", "CSE102", "CSE201")]
    assert all(
        course.rounds and course.rounds[0].window == window
        for course in teacher_page.context["courses"]
    )

    admin_page = office.web.get(reverse("accounts:dashboard_admin"))
    assert admin_page.context["home"].window == window
    assert admin_page.context["home"].open_now

    # f. everyone submits; a second try is refused
    for client in (alice_web, bob_web, carol_web):
        assert give_feedback(client, window, term.offerings["CSE101"]).status_code == 302
    assert give_feedback(alice_web, window, term.offerings["CSE101"]).status_code == 409
    assert FeedbackResponse.objects.filter(window=window).count() == 3
    _page, cards = student_cards(alice_web)
    assert cards["CSE101"].state == portal.CourseState.SUBMITTED
    assert cards["CSE102"].can_give

    # the round closes; the teacher now sees the report, and only above MIN_RESPONSES
    office.edit_round(
        window,
        opens_at=stamp(now - timedelta(hours=2)),
        closes_at=stamp(now - timedelta(minutes=1)),
    )
    lines = {
        course.offering.course.code: course.rounds[0]
        for course in teacher_web.get(reverse("accounts:dashboard_teacher")).context["courses"]
    }
    assert lines["CSE101"].summary.rate.submitted == 3
    assert lines["CSE101"].summary.average is not None
    assert lines["CSE102"].summary.rate is None  # nobody answered: held back
    report = teacher_web.get(
        reverse("reports:course", args=[term.offerings["CSE101"].pk, window.pk])
    )
    assert report.status_code == 200


def test_an_hod_registered_by_the_admin_sees_the_department(term):
    office, now = term.office, timezone.now()
    head = office.register_teacher("T-200", term.cse, role="hod")
    office.issue_codes(head)
    head_web = sign_up(office, head)
    assert head_web.get(reverse("accounts:dashboard")).url == reverse("accounts:dashboard_hod")
    window = office.open_round(
        term.current, "Mid-term", now - timedelta(hours=1), now + timedelta(days=3)
    )
    page = head_web.get(reverse("accounts:dashboard_hod"))
    assert page.status_code == 200
    assert page.context["window"] == window


# --- the boundaries that commonly break ------------------------------------------------------


def test_a_course_added_after_the_round_opened_gets_a_card(term):
    office, now = term.office, timezone.now()
    alice = office.register_student("S-001", term.cse, term.bsc, term.second)
    office.issue_codes(alice)
    alice_web = sign_up(office, alice)
    window = office.open_round(
        term.current, "Mid-term", now - timedelta(hours=1), now + timedelta(days=3)
    )
    _page, cards = student_cards(alice_web)
    assert set(cards) == {"CSE201"}  # the level/term rule enrolled her when she was registered
    office.enroll(alice, term.offerings["CSE101"], EnrollmentStatus.RETAKE)
    _page, cards = student_cards(alice_web)
    assert set(cards) == {"CSE101", "CSE201"}
    assert cards["CSE101"].window == window and cards["CSE101"].can_give


def test_a_round_opening_at_local_midnight_is_open_at_once(term):
    office = term.office
    alice = office.register_student("S-001", term.cse, term.bsc, term.first)
    today = semesters.today()
    window = office.open_round(
        term.current, "Today", local(today), local(today + timedelta(days=2))
    )
    midnight = local(today, 0, 0)
    assert window.opens_at == midnight
    assert window.status(midnight) == "open"
    assert window.status(midnight - timedelta(seconds=1)) == "upcoming"
    early = portal.build_dashboard(alice, midnight + timedelta(minutes=5))
    assert early.semester == term.current
    assert early.round.window == window
    assert {entry.offering.course.code for entry in early.entries} == {"CSE101"}


def test_a_semester_starting_today_in_dhaka_is_current_while_utc_is_still_yesterday(term):
    today = semesters.today()
    assert semesters.current_semester(today) == term.current
    utc_yesterday_evening = local(today, 0, 30).astimezone(UTC)
    assert utc_yesterday_evening.date() == today - timedelta(days=1)
    assert timezone.localdate(utc_yesterday_evening, timezone.get_default_timezone()) == today


def test_a_round_must_lie_inside_its_semester(term):
    office, now = term.office, timezone.now()
    response = office.open_round(
        term.previous,
        "Wrong semester",
        now - timedelta(hours=1),
        now + timedelta(days=1),
        expect=200,
    )
    assert "inside the semester" in response.content.decode()
    assert not FeedbackWindow.objects.exists()


def test_editing_the_semester_dates_moves_its_courses_in_and_out_of_view(term):
    office = term.office
    alice = office.register_student("S-001", term.cse, term.bsc, term.first)
    office.issue_codes(alice)
    alice_web = sign_up(office, alice)
    today = semesters.today()
    office.post(
        "academics:edit",
        {
            "season": term.current.season,
            "year": term.current.year,
            "start_date": (today + timedelta(days=1)).isoformat(),
            "end_date": (today + timedelta(days=90)).isoformat(),
        },
        "semesters",
        term.current.pk,
    )
    page, cards = student_cards(alice_web)
    assert not cards
    assert "No current semester" in page.content.decode()
    office.post(
        "academics:edit",
        {
            "season": term.current.season,
            "year": term.current.year,
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=90)).isoformat(),
        },
        "semesters",
        term.current.pk,
    )
    _page, cards = student_cards(alice_web)
    assert set(cards) == {"CSE101"}


def test_a_promoted_student_sees_the_new_level_and_keeps_a_retake(term):
    office = term.office
    alice = office.register_student("S-001", term.cse, term.bsc, term.first)
    office.issue_codes(alice)
    alice_web = sign_up(office, alice)
    office.post(
        "accounts:registry_edit",
        {
            "external_id": alice.registry.external_id,
            "full_name": "Student S-001",
            "department": term.cse.pk,
            "program": term.bsc.pk,
            "batch": "",
            "level_term": term.second.pk,
            "section": "",
            "academic_status": "active",
        },
        alice.registry_id,
    )
    _page, cards = student_cards(alice_web)
    # Already given courses stay (nothing is dropped behind the Admin's back); the new
    # level/term's courses are added by the same rule.
    assert set(cards) == {"CSE101", "CSE201"}


def test_a_course_not_offered_this_semester_is_refused(term):
    office = term.office
    alice = office.register_student("S-001", term.cse, term.bsc, term.first)
    response = office.enroll(alice, term.offerings["old"], expect=200)
    assert response.context["form"].errors
    assert not Enrollment.objects.filter(offering=term.offerings["old"]).exists()


def test_a_teacher_with_offerings_in_two_semesters_sees_only_the_current_one(term):
    office = term.office
    office.issue_codes(term.teacher)
    teacher_web = sign_up(office, term.teacher)
    page = teacher_web.get(reverse("accounts:dashboard_teacher"))
    assert term.offerings["old"] not in [course.offering for course in page.context["courses"]]
    assert offerings_for_teacher(term.teacher, term.current) == [
        term.offerings[code] for code in ("CSE101", "CSE102", "CSE201")
    ]


def test_every_screen_reads_the_same_course_list(term):
    office, now = term.office, timezone.now()
    alice = office.register_student("S-001", term.cse, term.bsc, term.first)
    office.enroll(alice, term.offerings["CSE201"], EnrollmentStatus.RETAKE)
    window = office.open_round(
        term.current, "Mid-term", now - timedelta(hours=1), now + timedelta(days=3)
    )
    listed = courses_for_student(alice, term.current)
    dashboard = portal.build_dashboard(alice, now)
    assert [entry.offering for entry in dashboard.entries] == listed
    for offering in listed:
        assert portal.find_target(alice, window.pk, offering.pk) == (offering, window)
    assert not SubmissionReceipt.objects.exists()
