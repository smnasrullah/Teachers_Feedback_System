"""The Admin panel (P16): home, university analytics, moderation, audit log, system settings.

Django test-client HTML tests. The 360px layout and the dark theme are checked by hand.
"""

import csv
import uuid
from datetime import date, timedelta
from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.urls import reverse
from django.utils import translation

from apps.academics.models import Course
from apps.analytics import services as analytics
from apps.auditlog.models import AuditEvent
from apps.auditlog.services import audit, search
from apps.core.models import SystemSetting
from apps.core.services import system_settings
from apps.enrollment.models import Enrollment
from apps.feedback.models import Answer, FeedbackResponse, ModerationStatus, SubmissionReceipt
from apps.feedback.services import anonymity, review
from tests.factories import (
    DepartmentFactory,
    LevelTermFactory,
    claim,
    make_admin,
    make_student,
    make_teacher,
    sign_in,
)
from tests.test_academics import make_course, make_offering, make_semester
from tests.test_feedback_core import make_window
from tests.test_hod_panel import CLOSED, COMMENT, OPEN, build, page

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _english():
    with translation.override("en"):
        yield


@pytest.fixture
def closed():
    return build(CLOSED)


@pytest.fixture
def open_round():
    return build(OPEN)


@pytest.fixture
def admin_client(web):
    sign_in(web, make_admin())
    return web


GET_URLS = (
    "accounts:dashboard_admin",
    "reports:analytics",
    "feedback:moderation",
    "auditlog:log",
    "auditlog:export",
    "core:settings",
)


def event(action="demo.thing", **fields):
    return audit.record(action, **fields)


def log_rows(client, **params):
    """The audit table's rows only (the filter's own drop-downs list every action name)."""
    body = page(client, reverse("auditlog:log"), **params)
    return body.split("<tbody")[1] if "<tbody" in body else ""


def flagged_answer(world, text="He is rude and the labs are fine", status=None):
    response = FeedbackResponse.objects.create(offering=world.offering, window=world.window)
    return Answer.objects.create(
        response=response,
        question=world.comment,
        encrypted_text=text,
        flagged=True,
        moderation=status or ModerationStatus.UNREVIEWED,
    )


class TestAccess:
    @pytest.mark.parametrize("name", GET_URLS)
    def test_signed_out_visitors_are_sent_to_login(self, web, name):
        assert web.get(reverse(name)).status_code == 302

    @pytest.mark.parametrize("name", GET_URLS)
    def test_nobody_but_the_admin_gets_in(self, web, closed, name):
        student = claim(make_student(closed.department))
        teacher = claim(make_teacher(closed.department))
        for user in (student, teacher, closed.hod):
            sign_in(web, user)
            assert web.get(reverse(name)).status_code == 403

    @pytest.mark.parametrize("name", GET_URLS)
    def test_the_admin_gets_in(self, admin_client, name):
        assert admin_client.get(reverse(name)).status_code == 200

    def test_posts_are_closed_to_everyone_else_too(self, web, closed):
        answer = flagged_answer(closed)
        targets = [
            (reverse("auditlog:verify"), {}),
            (reverse("feedback:moderation_decide", args=[answer.pk]), {"decision": "hide"}),
            (reverse("core:settings"), {"MIN_RESPONSES": "9"}),
        ]
        for user in (claim(make_teacher(closed.department)), closed.hod):
            sign_in(web, user)
            for url, data in targets:
                assert web.post(url, data).status_code == 403
        answer.refresh_from_db()
        assert answer.moderation == ModerationStatus.UNREVIEWED
        assert not SystemSetting.objects.exists()


class TestSystemSettings:
    def test_the_page_shows_every_setting(self, admin_client):
        body = page(admin_client, reverse("core:settings"))
        for key in system_settings.DEFINITIONS:
            assert f'name="{key}"' in body

    def test_a_change_is_stored_applied_and_audited(self, admin_client):
        assert anonymity.min_responses() == 5
        response = admin_client.post(reverse("core:settings"), self_values(MIN_RESPONSES="7"))
        assert response.status_code == 302
        assert anonymity.min_responses() == 7
        change = AuditEvent.objects.get(action="settings.changed")
        assert change.metadata == {"setting": "MIN_RESPONSES", "old": 5, "new": 7}
        assert change.actor_role == "admin"
        assert AuditEvent.objects.filter(action="settings.changed").count() == 1

    def test_saving_without_changes_audits_nothing(self, admin_client):
        admin_client.post(reverse("core:settings"), self_values())
        assert not AuditEvent.objects.filter(action="settings.changed").exists()
        assert not SystemSetting.objects.exists()

    @pytest.mark.parametrize("value", ["2", "0", "-1", "abc", "101", ""])
    def test_min_responses_below_the_floor_or_invalid_is_rejected(self, admin_client, value):
        response = admin_client.post(reverse("core:settings"), self_values(MIN_RESPONSES=value))
        assert response.status_code == 200
        assert anonymity.min_responses() == 5
        assert not SystemSetting.objects.exists()
        assert not AuditEvent.objects.filter(action="settings.changed").exists()

    def test_the_floor_message_names_the_limit(self, admin_client):
        body = admin_client.post(
            reverse("core:settings"), self_values(MIN_RESPONSES="2")
        ).content.decode()
        assert "cannot be below 3" in body

    def test_three_is_the_lowest_accepted_value(self, admin_client):
        admin_client.post(reverse("core:settings"), self_values(MIN_RESPONSES="3"))
        assert anonymity.min_responses() == 3

    def test_one_bad_value_stores_nothing(self, admin_client):
        values = self_values(MIN_RESPONSES="9", LOW_RATING_THRESHOLD="9")
        assert admin_client.post(reverse("core:settings"), values).status_code == 200
        assert not SystemSetting.objects.exists()

    def test_the_service_refuses_a_value_below_the_floor_too(self):
        with pytest.raises(ValidationError) as caught:
            system_settings.update({"MIN_RESPONSES": 2}, actor=make_admin())
        assert "MIN_RESPONSES" in caught.value.error_dict
        assert not SystemSetting.objects.exists()

    def test_a_stored_value_below_the_floor_still_cannot_lower_it(self):
        SystemSetting.objects.create(key="MIN_RESPONSES", value=1)
        system_settings.cache.clear()
        assert anonymity.min_responses() == 3

    def test_settings_are_cached_until_changed(self, django_assert_num_queries):
        system_settings.get("MIN_RESPONSES")
        with django_assert_num_queries(0):
            system_settings.get("MIN_RESPONSES")
            system_settings.get("PROFANITY_ACTION")
        system_settings.update({"MIN_RESPONSES": 6}, actor=make_admin())
        assert system_settings.get("MIN_RESPONSES") == 6

    def test_environment_defaults_apply_until_the_admin_changes_them(self, settings):
        settings.PROFANITY_ACTION = "mask"
        assert system_settings.get("PROFANITY_ACTION") == "mask"
        system_settings.update({"PROFANITY_ACTION": "remove"}, actor=make_admin())
        assert system_settings.get("PROFANITY_ACTION") == "remove"

    def test_reminder_hours_are_sorted_unique_and_limited(self):
        definition = system_settings.DEFINITIONS["REMINDER_HOURS_BEFORE_CLOSE"]
        assert definition.normalise("6, 48; 24, 48") == [48, 24, 6]
        assert definition.normalise("") == []
        for bad in ("0", "x", "721", "1,2,3,4,5,6"):
            with pytest.raises(ValidationError):
                definition.normalise(bad)

    def test_unknown_choices_are_refused(self):
        for key, value in (("PROFANITY_ACTION", "delete"), ("RESULTS_VISIBLE", "live")):
            with pytest.raises(ValidationError):
                system_settings.DEFINITIONS[key].normalise(value)

    def test_holding_results_back_hides_a_closed_round_from_teachers(self, closed):
        assert anonymity.results_visible(closed.window)
        system_settings.update({"RESULTS_VISIBLE": "held"}, actor=make_admin())
        assert not anonymity.results_visible(closed.window)

    def test_the_other_settings_reach_their_readers(self, closed):
        from apps.feedback.services import filter as comment_filter

        system_settings.update(
            {
                "PROFANITY_ACTION": "mask",
                "LOW_RATING_THRESHOLD": 4.5,
                "SHOW_OWN_ID_TO_STUDENT": True,
            },
            actor=make_admin(),
        )
        assert "idiot" not in comment_filter.clean("he is an idiot").text
        assert "*" in comment_filter.clean("he is an idiot").text
        from apps.reports.services import department

        assert department.threshold_from("junk") == 4.5


def self_values(**overrides):
    """A complete valid settings form, as the page would send it, with ``overrides``."""
    values = {
        "MIN_RESPONSES": "5",
        "LOW_RATING_THRESHOLD": "3.5",
        "PROFANITY_ACTION": "remove",
        "RESULTS_VISIBLE": "after_close",
        "DRAFT_RETENTION_DAYS": "30",
        "REMINDER_HOURS_BEFORE_CLOSE": "72, 24, 1",
        "REMINDER_ON_OPEN": "on",
        "QUIET_HOURS_START": "22",
        "QUIET_HOURS_END": "7",
    }
    values.update(overrides)
    return values


class TestAuditLog:
    def test_events_are_listed_newest_first(self, admin_client):
        event("demo.first")
        event("demo.second")
        rows = log_rows(admin_client)
        assert rows.index("demo.second") < rows.index("demo.first")

    def test_filter_by_actor_action_object_and_date(self, admin_client, closed):
        teacher = claim(make_teacher(closed.department))
        event("demo.mine", actor=teacher, target=closed.offering)
        event("demo.other")
        assert "demo.other" not in log_rows(admin_client, actor=teacher.username[:6])
        assert "demo.mine" in log_rows(admin_client, actor=teacher.username)
        by_action = log_rows(admin_client, action="demo.other")
        assert "demo.other" in by_action
        assert "demo.mine" not in by_action
        by_object = log_rows(
            admin_client, object_type="academics.courseoffering", object_id=closed.offering.pk
        )
        assert "demo.mine" in by_object
        assert "demo.other" not in by_object
        today = date.today().isoformat()
        assert "demo.mine" in log_rows(admin_client, date_from=today, date_to=today)
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        assert "demo.mine" not in log_rows(admin_client, date_from=tomorrow)
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        assert "demo.mine" not in log_rows(admin_client, date_to=yesterday)

    def test_an_end_date_before_the_start_is_an_error_and_filters_nothing(self, admin_client):
        event("demo.kept")
        body = page(
            admin_client, reverse("auditlog:log"), date_from="2026-05-02", date_to="2026-05-01"
        )
        assert "cannot be before the start date" in body
        assert "demo.kept" in body

    def test_export_follows_the_filters_and_is_audited(self, admin_client):
        event("demo.kept", metadata={"count": 2})
        event("demo.dropped")
        response = admin_client.get(reverse("auditlog:export"), {"action": "demo.kept"})
        assert response["Content-Type"].startswith("text/csv")
        assert "attachment" in response["Content-Disposition"]
        rows = list(csv.reader(StringIO(b"".join(response.streaming_content).decode())))
        assert rows[0] == list(search.EXPORT_COLUMNS)
        assert [row[4] for row in rows[1:]] == ["demo.kept"]
        assert '"count": 2' in rows[1][-1]
        exported = AuditEvent.objects.get(action="audit.exported")
        assert exported.metadata == {"filters": ["action"]}

    def test_export_cells_cannot_run_as_formulas(self):
        record = event("demo.formula", metadata={"note": "x"})
        assert record.pk
        lines = list(search.export_lines(AuditEvent.objects.all()))
        assert all(not cell.startswith("=") for cell in lines[1].split(","))
        from apps.core.csv_safe import safe_cell

        assert safe_cell("=1+1") == "'=1+1"

    def test_the_chain_check_reports_an_intact_trail(self, admin_client):
        event("demo.one")
        response = admin_client.post(reverse("auditlog:verify"), follow=True)
        assert "The audit trail is intact" in response.content.decode()
        assert AuditEvent.objects.filter(action="audit.chain_verified").exists()

    @pytest.mark.skipif(connection.vendor == "postgresql", reason="PostgreSQL refuses tampering")
    def test_the_chain_check_names_a_tampered_event(self, admin_client):
        first, _second = event("demo.one"), event("demo.two")
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE auditlog_auditevent SET action = %s WHERE id = %s",
                ["demo.edited", first.pk],
            )
        body = admin_client.post(reverse("auditlog:verify"), follow=True).content.decode()
        assert "The audit trail was changed" in body
        assert f"event {first.pk}" in body

    def test_verification_is_post_only(self, admin_client):
        assert admin_client.get(reverse("auditlog:verify")).status_code == 405


class TestModeration:
    def test_the_queue_shows_cleaned_text_only(self, admin_client, closed):
        flagged_answer(closed, "Good but he is an")
        Answer.objects.create(
            response=FeedbackResponse.objects.create(
                offering=closed.offering, window=closed.window
            ),
            question=closed.comment,
            encrypted_text="Perfectly fine comment",
        )
        body = page(admin_client, reverse("feedback:moderation"))
        assert "Good but he is an" in body
        assert "Perfectly fine comment" not in body
        assert closed.offering.course.code not in body
        assert closed.window.name not in body

    def test_approving_keeps_the_text_and_leaves_the_queue(self, admin_client, closed):
        answer = flagged_answer(closed, "Good but he is an")
        url = reverse("feedback:moderation_decide", args=[answer.pk])
        assert admin_client.post(url, {"decision": "approve"}).status_code == 302
        answer.refresh_from_db()
        assert answer.moderation == ModerationStatus.APPROVED
        assert answer.encrypted_text == "Good but he is an"
        assert review.queue_size() == 0
        event_row = AuditEvent.objects.get(action="moderation.approved")
        assert event_row.object_id == str(answer.pk)
        assert event_row.metadata == {"previous": "unreviewed"}
        assert "Good but he is an" not in str(event_row.metadata)
        approved = page(admin_client, reverse("feedback:moderation"), view="approved")
        assert "Good but he is an" in approved

    def test_hiding_removes_the_comment_from_every_report(self, admin_client, closed):
        closed.submit(closed.offering, count=6, text="Plain feedback")
        victim = flagged_answer(closed, "Hide me please")
        admin_client.post(
            reverse("feedback:moderation_decide", args=[victim.pk]), {"decision": "hide"}
        )
        sign_in(admin_client, claim(closed.offering.teacher))
        body = page(admin_client, closed.report_url(closed.offering))
        assert "Plain feedback" in body
        assert "Hide me please" not in body
        texts = [
            comment.text
            for comment in analytics.comment_list(
                closed.window, closed.offering, closed.comment, viewer=closed.hod
            )
        ]
        assert "Hide me please" not in texts
        assert "Plain feedback" in texts

    def test_a_decision_can_be_reversed(self, admin_client, closed):
        answer = flagged_answer(closed, "Hidden then restored")
        url = reverse("feedback:moderation_decide", args=[answer.pk])
        admin_client.post(url, {"decision": "hide"})
        hidden = page(admin_client, reverse("feedback:moderation"), view="hidden")
        assert "Hidden then restored" in hidden
        admin_client.post(url, {"decision": "approve"})
        answer.refresh_from_db()
        assert answer.moderation == ModerationStatus.APPROVED
        assert list(
            AuditEvent.objects.filter(action__startswith="moderation.").values_list(
                "metadata", flat=True
            )
        ) == [
            {"previous": "unreviewed"},
            {"previous": "hidden"},
        ]

    def test_bad_decisions_and_unknown_comments_are_not_found(self, admin_client, closed):
        answer = flagged_answer(closed)
        assert (
            admin_client.post(
                reverse("feedback:moderation_decide", args=[answer.pk]), {"decision": "edit"}
            ).status_code
            == 404
        )
        assert (
            admin_client.post(
                reverse("feedback:moderation_decide", args=[uuid.uuid4()]), {"decision": "hide"}
            ).status_code
            == 404
        )
        answer.refresh_from_db()
        assert answer.moderation == ModerationStatus.UNREVIEWED

    def test_the_text_can_never_be_edited_through_the_screen(self, admin_client, closed):
        answer = flagged_answer(closed, "Original")
        admin_client.post(
            reverse("feedback:moderation_decide", args=[answer.pk]),
            {"decision": "approve", "encrypted_text": "Changed", "text": "Changed"},
        )
        answer.refresh_from_db()
        assert answer.encrypted_text == "Original"


@pytest.fixture
def teacher_client(web, closed):
    closed.submit(closed.offering, count=6, text="Rude lecturer")
    sign_in(web, claim(closed.offering.teacher))
    return web


class TestTeacherReports:
    def reportable(self, teacher_client, closed):
        body = page(teacher_client, closed.report_url(closed.offering))
        assert "Report this comment" in body
        start = body.index('name="comment" value="') + len('name="comment" value="')
        return body[start : body.index('"', start)]

    def test_a_teacher_reports_a_comment_into_the_queue(self, teacher_client, closed):
        token = self.reportable(teacher_client, closed)
        url = reverse("reports:report_comment", args=[closed.offering.pk, closed.window.pk])
        assert teacher_client.post(url, {"comment": token}).status_code == 302
        assert review.queue_size() == 1
        reported = Answer.objects.get(moderation=ModerationStatus.REPORTED)
        assert reported.encrypted_text == "Rude lecturer"
        assert AuditEvent.objects.get(action="moderation.reported").object_id == str(reported.pk)
        sign_in(teacher_client, make_admin())
        assert "Reported by a teacher" in page(teacher_client, reverse("feedback:moderation"))

    def test_the_report_page_never_carries_the_answer_id(self, teacher_client, closed):
        body = page(teacher_client, closed.report_url(closed.offering))
        for answer in Answer.objects.all():
            assert str(answer.pk) not in body

    def test_a_reported_comment_cannot_be_reported_twice(self, teacher_client, closed):
        token = self.reportable(teacher_client, closed)
        url = reverse("reports:report_comment", args=[closed.offering.pk, closed.window.pk])
        teacher_client.post(url, {"comment": token})
        teacher_client.post(url, {"comment": token})
        assert AuditEvent.objects.filter(action="moderation.reported").count() == 1

    def test_unknown_tokens_are_not_found(self, teacher_client, closed):
        url = reverse("reports:report_comment", args=[closed.offering.pk, closed.window.pk])
        for token in ("", "nope", "0" * 32):
            assert teacher_client.post(url, {"comment": token}).status_code == 404
        assert review.queue_size() == 0

    def test_another_teacher_cannot_report_on_this_course(self, web, closed, teacher_client):
        token = self.reportable(teacher_client, closed)
        stranger = claim(make_teacher(closed.department))
        sign_in(web, stranger)
        url = reverse("reports:report_comment", args=[closed.offering.pk, closed.window.pk])
        assert web.post(url, {"comment": token}).status_code == 403
        assert review.queue_size() == 0

    def test_a_head_of_department_cannot_report(self, web, closed, teacher_client):
        token = self.reportable(teacher_client, closed)
        sign_in(web, closed.hod)
        url = reverse("reports:report_comment", args=[closed.offering.pk, closed.window.pk])
        assert web.post(url, {"comment": token}).status_code == 403

    def test_a_token_from_another_course_names_nothing_here(self, web, closed, teacher_client):
        token = self.reportable(teacher_client, closed)
        closed.submit(closed.colleague_offering, count=6, text="Other course")
        sign_in(web, claim(closed.colleague_offering.teacher))
        url = reverse(
            "reports:report_comment", args=[closed.colleague_offering.pk, closed.window.pk]
        )
        assert web.post(url, {"comment": token}).status_code == 404

    def test_nothing_can_be_reported_while_the_round_is_open(self, web, open_round):
        open_round.submit(open_round.offering, count=6, text="Early")
        sign_in(web, claim(open_round.offering.teacher))
        url = reverse("reports:report_comment", args=[open_round.offering.pk, open_round.window.pk])
        assert web.post(url, {"comment": "0" * 32}).status_code == 404

    def test_nothing_can_be_reported_below_the_response_floor(self, web, closed):
        closed.submit(closed.offering, count=2, text="Few")
        sign_in(web, claim(closed.offering.teacher))
        url = reverse("reports:report_comment", args=[closed.offering.pk, closed.window.pk])
        assert web.post(url, {"comment": "0" * 32}).status_code == 404

    def test_the_form_needs_a_post(self, teacher_client, closed):
        url = reverse("reports:report_comment", args=[closed.offering.pk, closed.window.pk])
        assert teacher_client.get(url).status_code == 405


class TestHome:
    def test_the_tiles_and_quick_actions(self, admin_client, open_round):
        flagged_answer(open_round)
        body = page(admin_client, reverse("accounts:dashboard_admin"))
        assert "Registered users" in body
        assert "Closes in" in body and "data-countdown-to=" in body
        assert "Comments to review" in body
        for name in (
            "academics:import_index",
            "feedback:window_create",
            "academics:promotion",
            "feedback:questions",
        ):
            assert f'href="{reverse(name)}"' in body
        assert reverse("feedback:moderation") in body

    def test_the_counts_are_right(self, web, open_round):
        admin = make_admin()
        claim(make_student(open_round.department))
        claim(make_teacher(open_round.department))
        sign_in(web, admin)
        body = page(web, reverse("accounts:dashboard_admin"))
        assert "1 students, 2 teachers" in body
        flagged_answer(open_round)
        flagged_answer(open_round, status=ModerationStatus.REPORTED)
        flagged_answer(open_round, status=ModerationStatus.HIDDEN)
        assert review.queue_size() == 2
        assert ">2</div>" in page(web, reverse("accounts:dashboard_admin"))

    def test_participation_by_department_needs_enough_submissions(self, admin_client, open_round):
        open_round.submit(open_round.offering, count=2)
        body = page(admin_client, reverse("accounts:dashboard_admin"))
        assert "Department figures appear once enough forms have been submitted." in body

    def test_participation_shows_once_the_threshold_is_met(self, admin_client, open_round):
        open_round.submit(open_round.offering, count=6)
        body = page(admin_client, reverse("accounts:dashboard_admin"))
        assert "6 of 6 forms submitted" in body
        assert "100%" in body

    def test_recent_activity_leaves_out_students(self, admin_client, closed):
        event("demo.staff", actor=make_admin())
        event("demo.student", actor=claim(make_student(closed.department)))
        body = page(admin_client, reverse("accounts:dashboard_admin"))
        assert "demo.staff" in body
        assert "demo.student" not in body

    def test_the_home_works_with_no_round_at_all(self, admin_client):
        body = page(admin_client, reverse("accounts:dashboard_admin"))
        assert "No feedback round has started yet." in body


class TestAnalytics:
    def second_department(self, closed):
        other = DepartmentFactory()
        offering = make_offering(
            make_course(other, code="EEE101", level_term=closed.offering.course.level_term),
            closed.semester,
        )
        return other, offering

    def test_an_open_round_shows_no_ratings(self, admin_client, open_round):
        open_round.submit(open_round.offering, count=6, rating=5)
        body = page(admin_client, reverse("reports:analytics"))
        assert "Results are released after the round closes." in body
        assert "CSE201" not in body

    def test_a_closed_round_shows_distribution_departments_and_rankings(self, admin_client, closed):
        other, offering = self.second_department(closed)
        closed.submit(closed.offering, count=6, rating=5)
        closed.submit(offering, count=6, rating=2)
        body = page(admin_client, reverse("reports:analytics"))
        assert "Rating distribution" in body
        assert 'id="distribution"' in body
        assert "Department comparison" in body
        assert closed.department.code in body
        assert other.code in body
        assert body.index("CSE201") < body.index("EEE101")
        assert "Top courses" in body

    def test_small_groups_show_no_numbers(self, admin_client, closed):
        closed.submit(closed.offering, count=2, rating=5)
        body = page(admin_client, reverse("reports:analytics"))
        assert "CSE201" not in body
        assert 'id="distribution"' not in body
        assert "Not enough responses to show this." in body

    def test_the_department_filter_narrows_every_figure(self, admin_client, closed):
        other, offering = self.second_department(closed)
        closed.submit(closed.offering, count=6, rating=5)
        closed.submit(offering, count=6, rating=2)
        body = page(admin_client, reverse("reports:analytics"), department=other.pk)
        assert "EEE101" in body
        assert "CSE201" not in body
        assert (
            closed.department.code
            not in body.split("Department comparison")[1].split("Top courses")[0]
        )

    def test_the_level_term_filter_narrows_the_courses(self, admin_client, closed):
        _other, offering = self.second_department(closed)
        elsewhere = make_offering(
            make_course(closed.department, code="CSE999", level_term=LevelTermFactory()),
            closed.semester,
        )
        closed.submit(closed.offering, count=6, rating=4)
        closed.submit(elsewhere, count=6, rating=4)
        closed.submit(offering, count=6, rating=4)
        level = closed.offering.course.level_term
        body = page(admin_client, reverse("reports:analytics"), level_term=level.pk)
        assert "CSE201" in body
        assert "EEE101" in body
        assert "CSE999" not in body

    def test_the_round_and_semester_filters_pick_the_round(self, admin_client, closed):
        later = make_semester(
            season="summer", year=2026, start_date=date(2026, 7, 1), end_date=date(2026, 12, 31)
        )
        later_window = make_window(later, name="Final", **CLOSED)
        body = page(admin_client, reverse("reports:analytics"), round=later_window.pk)
        assert "Summer 2026, Final" in body
        body = page(admin_client, reverse("reports:analytics"), semester=closed.semester.pk)
        assert closed.window.name in body
        assert "Summer 2026, Final" not in body

    def test_a_round_of_another_semester_is_an_error(self, admin_client, closed):
        later = make_semester(start_date=date(2026, 7, 1), end_date=date(2026, 12, 31))
        make_window(later, name="Final", **CLOSED)
        body = page(
            admin_client,
            reverse("reports:analytics"),
            semester=later.pk,
            round=closed.window.pk,
        )
        assert "belongs to another semester" in body

    def test_junk_filters_are_ignored(self, admin_client, closed):
        body = page(admin_client, reverse("reports:analytics"), department="x", round="99999")
        assert "University analytics" in body

    def test_holding_results_hides_the_ratings_here_too(self, admin_client, closed):
        closed.submit(closed.offering, count=6, rating=5)
        system_settings.update({"RESULTS_VISIBLE": "held"}, actor=make_admin())
        body = page(admin_client, reverse("reports:analytics"))
        assert "CSE201" not in body
        assert 'id="distribution"' not in body

    def test_it_works_with_no_round(self, admin_client):
        body = page(admin_client, reverse("reports:analytics"))
        assert "No feedback round yet" in body

    def test_no_comment_text_or_student_identity_appears(self, admin_client, closed):
        closed.submit(closed.offering, count=6, rating=4, text=COMMENT)
        enrolled = Enrollment.objects.filter(offering=closed.offering).first()
        body = page(admin_client, reverse("reports:analytics"))
        assert COMMENT not in body
        assert enrolled.student_profile.registry.external_id not in body
        assert SubmissionReceipt.objects.exists()
        assert Course.objects.filter(code="CSE201").exists()
