"""The head of department's panel (P15): overview, drill-down, pending list, reminders, audit.

Django test-client HTML tests. The 360px layout and the dark theme are checked by hand.
"""

import re
from dataclasses import dataclass
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import translation

from apps.academics.models import CourseOffering
from apps.auditlog.models import AuditEvent
from apps.auditlog.services import audit
from apps.enrollment.models import Enrollment
from apps.feedback.models import (
    Answer,
    FeedbackResponse,
    FeedbackWindow,
    Question,
    QuestionCategory,
    QuestionType,
    SubmissionReceipt,
)
from apps.notifications.models import ReminderRequest
from apps.reports.models import ActionNote
from apps.reports.services import department as service
from tests.factories import (
    DepartmentFactory,
    claim,
    make_admin,
    make_hod,
    make_student,
    make_teacher,
    sign_in,
)
from tests.test_academics import make_course, make_offering, make_semester
from tests.test_feedback_core import make_question, make_window

pytestmark = pytest.mark.django_db

CLOSED = {"opens": timedelta(days=-3), "closes": timedelta(days=-1)}
OPEN = {"opens": timedelta(days=-1), "closes": timedelta(days=2)}
OWN_ID = "2101555"
FOREIGN_ID = "2209777"
COMMENT = "The lecturer shouts at the back row"


@pytest.fixture(autouse=True)
def _english():
    with translation.override("en"):
        yield


@dataclass
class World:
    department: object
    hod: object
    semester: object
    window: FeedbackWindow
    offering: CourseOffering
    colleague_offering: CourseOffering
    foreign_offering: CourseOffering
    rating: Question
    comment: Question

    def submit(self, offering, count=6, rating=4, window=None, text=COMMENT):
        """``count`` students of the offering's own department answer and get receipts."""
        window = window or self.window
        for _ in range(count):
            student = make_student(offering.course.department)
            Enrollment.objects.create(student_profile=student, offering=offering)
            SubmissionReceipt.objects.create(
                student_profile=student, offering=offering, window=window
            )
            response = FeedbackResponse.objects.create(offering=offering, window=window)
            Answer.objects.create(response=response, question=self.rating, int_value=rating)
            Answer.objects.create(response=response, question=self.comment, encrypted_text=text)

    def enroll(self, department, offering=None, external_id=None):
        student = make_student(department, external_id=external_id)
        Enrollment.objects.create(student_profile=student, offering=offering or self.offering)
        return student

    def report_url(self, offering):
        return reverse("reports:course", args=[offering.pk, self.window.pk])


def build(window_kind):
    department = DepartmentFactory()
    hod = make_hod(department)
    semester = make_semester(current=True)
    category = QuestionCategory.objects.get_or_create(name="Teaching")[0]
    return World(
        department=department,
        hod=hod,
        semester=semester,
        window=make_window(semester, **window_kind),
        offering=make_offering(make_course(department, code="CSE201"), semester),
        colleague_offering=make_offering(make_course(department, code="CSE202"), semester),
        foreign_offering=make_offering(make_course(DepartmentFactory(), code="EEE301"), semester),
        rating=make_question(QuestionType.RATING, category=category, order=1),
        comment=make_question(QuestionType.TEXT, order=2),
    )


@pytest.fixture
def closed():
    return build(CLOSED)


@pytest.fixture
def open_round():
    return build(OPEN)


def page(client, url, **params):
    response = client.get(url, params)
    assert response.status_code == 200
    return response.content.decode()


def hod_client(web, world):
    sign_in(web, world.hod)
    return web


HOD_URLS = ("accounts:dashboard_hod", "reports:hod_pending", "reports:hod_audit")


class TestAccess:
    def test_only_the_head_of_department_gets_in(self, web, closed):
        for name in HOD_URLS:
            assert web.get(reverse(name)).status_code == 302
        for user in (
            claim(make_teacher(closed.department)),
            claim(make_student(closed.department)),
            make_admin(),
        ):
            sign_in(web, user)
            for name in HOD_URLS:
                assert web.get(reverse(name)).status_code == 403, name
            assert web.post(reverse("reports:hod_remind")).status_code == 403

    def test_head_of_another_department_cannot_open_a_foreign_report(self, web, closed):
        closed.submit(closed.foreign_offering)
        hod_client(web, closed)
        assert web.get(closed.report_url(closed.foreign_offering)).status_code == 403
        assert web.get(closed.report_url(closed.offering)).status_code == 200

    def test_head_sees_the_department_nav_entries(self, web, closed):
        body = page(hod_client(web, closed), reverse("accounts:dashboard_hod"))
        assert reverse("reports:hod_pending") in body
        assert reverse("reports:hod_audit") in body

    def test_heads_own_teacher_view_still_works(self, web, closed):
        assert web.get(reverse("reports:overview")).status_code == 302
        assert page(hod_client(web, closed), reverse("reports:overview"))


class TestOverview:
    def test_no_round_shows_an_empty_state(self, web):
        world = build(CLOSED)
        FeedbackWindow.objects.all().delete()
        assert "No feedback round yet" in page(hod_client(web, world), reverse(HOD_URLS[0]))

    def test_open_round_holds_every_figure_back(self, web, open_round):
        open_round.submit(open_round.offering)
        body = page(hod_client(web, open_round), reverse(HOD_URLS[0]))
        assert "Results are released after the round closes." in body
        assert "CSE201" in body
        assert 'class="heat-' not in body
        assert 'class="stars"' not in body

    def test_ranking_orders_the_department_and_leaves_other_departments_out(self, web, closed):
        closed.submit(closed.offering, rating=5)
        closed.submit(closed.colleague_offering, rating=4)
        closed.submit(closed.foreign_offering, rating=1)
        body = page(hod_client(web, closed), reverse(HOD_URLS[0]))
        assert body.index("CSE201") < body.index("CSE202")
        assert "EEE301" not in body
        assert re.search(r"CSE201.*?5\.0", body, re.S)

    def test_a_course_below_the_threshold_gets_an_alert_card(self, web, closed):
        closed.submit(closed.offering, rating=5)
        closed.submit(closed.colleague_offering, rating=2)
        client = hod_client(web, closed)
        body = page(client, reverse(HOD_URLS[0]))
        assert "Courses below 3.5" in body
        assert "No action note yet." in body
        assert "Courses below" not in page(client, reverse(HOD_URLS[0]), below="1.5")
        assert "Courses below 5.0" in page(client, reverse(HOD_URLS[0]), below="9")

    def test_threshold_input_is_clamped_and_defaults_to_the_setting(self, settings):
        settings.LOW_RATING_THRESHOLD = 3.2
        assert service.threshold_from("") == 3.2
        assert service.threshold_from("nan") == 3.2
        assert service.threshold_from("inf") == 3.2
        assert service.threshold_from("0") == 1.0
        assert service.threshold_from("4.25") == 4.25

    def test_a_group_below_the_response_floor_shows_no_number(self, web, closed):
        closed.submit(closed.offering, count=2, rating=5)
        body = page(hod_client(web, closed), reverse(HOD_URLS[0]))
        assert "Not enough responses to show this." in body
        assert 'class="heat-' not in body
        assert "Courses below" not in body

    def test_heatmap_shows_the_number_as_well_as_the_colour(self, web, closed):
        closed.submit(closed.offering, rating=4)
        body = page(hod_client(web, closed), reverse(HOD_URLS[0]))
        assert re.search(r'class="heat-4 num">4\.0<', body)
        assert "Teaching" in body

    def test_action_notes_are_listed_for_the_head(self, web, closed):
        closed.submit(closed.offering, rating=2)
        ActionNote.objects.create(
            offering=closed.offering, window=closed.window, text="Extra tutorials from week 3"
        )
        body = page(hod_client(web, closed), reverse(HOD_URLS[0]))
        assert "Extra tutorials from week 3" in body
        assert "The teacher has written an action note." in body

    def test_no_view_shows_comment_text(self, web, closed):
        closed.submit(closed.offering)
        client = hod_client(web, closed)
        for name in HOD_URLS:
            assert COMMENT not in page(client, reverse(name))


class TestDrillDown:
    def test_head_reads_a_colleagues_report_and_note_without_editing(self, web, closed):
        closed.submit(closed.colleague_offering)
        ActionNote.objects.create(
            offering=closed.colleague_offering, window=closed.window, text="Reworked the labs"
        )
        client = hod_client(web, closed)
        body = page(client, closed.report_url(closed.colleague_offering))
        assert "Reworked the labs" in body
        assert "Save note" not in body
        assert reverse("accounts:dashboard_hod") in body
        note_url = reverse("reports:note", args=[closed.colleague_offering.pk, closed.window.pk])
        assert client.post(note_url, {"text": "mine now"}).status_code == 403
        assert ActionNote.objects.get().text == "Reworked the labs"


class TestPending:
    def test_own_students_are_listed_with_ids_and_foreign_ones_only_counted(self, web, closed):
        closed.enroll(closed.department, external_id=OWN_ID)
        foreign = DepartmentFactory()
        closed.enroll(foreign, external_id=FOREIGN_ID)
        closed.enroll(foreign, external_id="2209778")
        body = page(hod_client(web, closed), reverse("reports:hod_pending"))
        assert OWN_ID in body
        assert FOREIGN_ID not in body
        assert "2209778" not in body
        assert "2 students of other departments have not submitted" in body
        assert "1 student of your department has not submitted" in body

    def test_foreign_ids_stay_hidden_under_every_filter_and_page(self, web, closed):
        for index in range(30):
            closed.enroll(closed.department, external_id=f"2101{index:03d}")
        outsider = closed.enroll(DepartmentFactory(), external_id=FOREIGN_ID)
        client = hod_client(web, closed)
        url = reverse("reports:hod_pending")
        variants = [
            {},
            {"page": 2},
            {"course": closed.offering.pk},
            {"level": outsider.level_term_id},
            {"course": closed.offering.pk, "level": outsider.level_term_id, "page": 9},
        ]
        for params in variants:
            assert FOREIGN_ID not in page(client, url, **params)

    def test_submitted_students_are_not_listed_and_the_list_filters(self, web, closed):
        closed.submit(closed.offering, count=1)
        waiting = closed.enroll(closed.department, closed.offering, external_id=OWN_ID)
        elsewhere = closed.enroll(closed.department, closed.colleague_offering, "2101999")
        client = hod_client(web, closed)
        url = reverse("reports:hod_pending")
        everyone = page(client, url)
        assert OWN_ID in everyone and "2101999" in everyone
        one_course = page(client, url, course=closed.offering.pk)
        assert OWN_ID in one_course and "2101999" not in one_course
        one_level = page(client, url, level=elsewhere.level_term_id)
        assert "2101999" in one_level and OWN_ID not in one_level
        assert waiting.level_term_id != elsewhere.level_term_id

    def test_course_of_another_department_is_refused(self, web, closed):
        client = hod_client(web, closed)
        url = reverse("reports:hod_pending")
        assert client.get(url, {"course": closed.foreign_offering.pk}).status_code == 403

    def test_round_defaults_to_the_open_one(self, web, closed):
        later = make_window(closed.semester, name="Final", **OPEN)
        closed.enroll(closed.department, external_id=OWN_ID)
        body = page(hod_client(web, closed), reverse("reports:hod_pending"))
        assert later.name in body
        assert "Remind" in body

    def test_closed_round_lists_but_offers_no_reminder(self, web, closed):
        closed.enroll(closed.department, external_id=OWN_ID)
        body = page(hod_client(web, closed), reverse("reports:hod_pending"))
        assert OWN_ID in body
        assert "reminders cannot be sent" in body
        assert reverse("reports:hod_remind") not in body

    def test_student_id_helper_is_the_policy_not_the_page(self, closed):
        student = closed.enroll(closed.department, external_id=OWN_ID)
        foreign = closed.enroll(DepartmentFactory(), external_id=FOREIGN_ID)
        found = service.pending_list(
            closed.department, closed.window, closed.hod, [closed.offering]
        )
        assert [row.student.pk for row in found.rows] == [student.pk]
        assert found.rows[0].student.visible_student_id == OWN_ID
        assert found.others == 1
        assert foreign.pk not in {row.student.pk for row in found.rows}


class TestReminders:
    def remind(self, client, world, **data):
        data.setdefault("window", world.window.pk)
        data.setdefault("offering", world.offering.pk)
        return client.post(reverse("reports:hod_remind"), data)

    def test_one_student_is_queued_once_and_audited(self, web, open_round):
        student = open_round.enroll(open_round.department, external_id=OWN_ID)
        other = open_round.enroll(open_round.department)
        client = hod_client(web, open_round)
        for _ in range(2):
            response = self.remind(client, open_round, student=student.pk)
            assert response.status_code == 302
        request = ReminderRequest.objects.get()
        assert request.student_profile_id == student.pk
        assert not ReminderRequest.objects.filter(student_profile=other).exists()
        event = AuditEvent.objects.get(action="hod.reminder_queued", metadata__count=0)
        assert event.department_id == open_round.department.pk
        assert AuditEvent.objects.filter(action="hod.reminder_queued").count() == 2

    def test_answer_is_the_same_for_one_and_for_all(self, web, open_round):
        student = open_round.enroll(open_round.department)
        open_round.enroll(DepartmentFactory())
        client = hod_client(web, open_round)
        single = self.remind(client, open_round, student=student.pk)
        bulk = self.remind(client, open_round)
        assert single.status_code == bulk.status_code == 302
        messages = [
            m.message for m in client.get(reverse("reports:hod_pending")).context["messages"]
        ]
        assert set(messages) == {"The reminder was queued."}

    def test_bulk_reaches_other_departments_without_listing_them(self, web, open_round):
        open_round.enroll(open_round.department)
        outsider = open_round.enroll(DepartmentFactory(), external_id=FOREIGN_ID)
        client = hod_client(web, open_round)
        self.remind(client, open_round)
        assert ReminderRequest.objects.count() == 2
        assert ReminderRequest.objects.filter(student_profile=outsider).exists()
        body = page(client, reverse("reports:hod_pending"))
        assert FOREIGN_ID not in body

    def test_a_student_of_another_department_cannot_be_named(self, web, open_round):
        outsider = open_round.enroll(DepartmentFactory(), external_id=FOREIGN_ID)
        client = hod_client(web, open_round)
        assert self.remind(client, open_round, student=outsider.pk).status_code == 403
        assert not ReminderRequest.objects.exists()

    def test_a_student_who_already_submitted_is_refused(self, web, open_round):
        student = open_round.enroll(open_round.department)
        SubmissionReceipt.objects.create(
            student_profile=student, offering=open_round.offering, window=open_round.window
        )
        client = hod_client(web, open_round)
        assert self.remind(client, open_round, student=student.pk).status_code == 403
        assert not ReminderRequest.objects.exists()

    def test_offering_of_another_department_is_refused(self, web, open_round):
        outsider = open_round.enroll(DepartmentFactory(), open_round.foreign_offering)
        client = hod_client(web, open_round)
        response = self.remind(
            client, open_round, offering=open_round.foreign_offering.pk, student=outsider.pk
        )
        assert response.status_code == 403
        assert not ReminderRequest.objects.exists()

    def test_closed_round_queues_nothing(self, web, closed):
        student = closed.enroll(closed.department)
        client = hod_client(web, closed)
        response = self.remind(client, closed, student=student.pk)
        assert response.status_code == 302
        assert not ReminderRequest.objects.exists()
        messages = [
            m.message for m in client.get(reverse("reports:hod_pending")).context["messages"]
        ]
        assert messages == ["Reminders can only be sent while the round is open."]

    def test_bad_input_is_a_404_or_403_never_a_crash(self, web, open_round):
        client = hod_client(web, open_round)
        assert self.remind(client, open_round, student="abc").status_code == 404
        assert self.remind(client, open_round, offering="x").status_code == 403
        assert self.remind(client, open_round, window=99999).status_code == 404

    def test_get_is_not_allowed(self, web, open_round):
        assert hod_client(web, open_round).get(reverse("reports:hod_remind")).status_code == 405


class TestAudit:
    def test_shows_staff_events_of_the_department_only(self, web, closed):
        staff = claim(make_teacher(closed.department))
        audit.record("enrollment.created", actor=staff, department_id=closed.department.pk)
        audit.record("enrollment.removed", actor=staff, department_id=DepartmentFactory().pk)
        student = claim(make_student(closed.department))
        audit.record("feedback.submitted", actor=student, department_id=closed.department.pk)
        audit.record("auth.login", actor=student, department_id=closed.department.pk)
        body = page(hod_client(web, closed), reverse("reports:hod_audit"))
        assert "enrollment.created" in body
        assert "enrollment.removed" not in body
        assert "feedback.submitted" not in body
        assert student.get_username() not in body

    def test_filters_by_action_and_hides_network_details(self, web, closed):
        staff = claim(make_teacher(closed.department))
        audit.record("enrollment.created", actor=staff, department_id=closed.department.pk)
        audit.record("registry.updated", actor=staff, department_id=closed.department.pk)
        client = hod_client(web, closed)
        body = page(client, reverse("reports:hod_audit"), action="registry.updated")
        assert "registry.updated" in body
        assert '<td role="cell" data-label="Action">enrollment.created' not in body
        assert "IP address" not in body
        assert "registry.updated" in page(client, reverse("reports:hod_audit"), action="nope")


class TestBangla:
    def test_every_head_page_renders_in_bangla(self, web, open_round):
        open_round.enroll(open_round.department, external_id=OWN_ID)
        client = hod_client(web, open_round)
        client.defaults["HTTP_ACCEPT_LANGUAGE"] = "bn"
        with translation.override("bn"):
            expected = {
                "accounts:dashboard_hod": "বিভাগের সারসংক্ষেপ",
                "reports:hod_pending": "অপেক্ষমাণ মতামত",
                "reports:hod_audit": "বিভাগের অডিট লগ",
            }
            for name, title in expected.items():
                assert title in page(client, reverse(name))
