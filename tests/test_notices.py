"""Notifications (P18): quiet hours, reminders, head-of-department reminders, result notices,
the bell, message templates and the delivery log.

The clock is set by passing ``now`` to the services (all times Asia/Dhaka, UTC+6).
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone, translation

from apps.auditlog.models import AuditEvent
from apps.core.services import system_settings
from apps.enrollment.models import Enrollment
from apps.feedback.models import FeedbackWindow, SubmissionReceipt
from apps.notifications.models import (
    DeliveryLog,
    Dispatch,
    Kind,
    MessageTemplate,
    Notification,
    ReminderRequest,
)
from apps.notifications.services import delivery, editor, inbox, messages, schedule
from tests import outbox
from tests.factories import claim, make_admin, make_hod, make_student, make_teacher, sign_in
from tests.test_academics import make_course, make_offering, make_semester

pytestmark = pytest.mark.django_db

DHAKA = ZoneInfo("Asia/Dhaka")
OPENS = datetime(2026, 3, 10, 9, 0, tzinfo=DHAKA)
CLOSES = OPENS + timedelta(days=7)


def at(day, hour, minute=0):
    return datetime(2026, 3, day, hour, minute, tzinfo=DHAKA)


class World:
    """One round, one course, and helpers to add students and teachers."""

    def __init__(self):
        self.semester = make_semester()
        self.window = FeedbackWindow.objects.create(
            semester=self.semester, name="Mid-term", opens_at=OPENS, closes_at=CLOSES
        )
        self.course = make_course()
        self.department = self.course.department
        self.teacher_profile = make_teacher(self.department)
        self.teacher = claim(self.teacher_profile, language="en")
        self.offering = make_offering(self.course, self.semester, self.teacher_profile)

    def student(self, **user_fields):
        profile = make_student(self.department)
        user = claim(profile, **{"language": "en", **user_fields})
        Enrollment.objects.create(student_profile=profile, offering=self.offering)
        return profile, user

    def submit(self, profile):
        SubmissionReceipt.objects.create(
            student_profile=profile, offering=self.offering, window=self.window
        )


@pytest.fixture
def world():
    return World()


@pytest.fixture(autouse=True)
def english():
    with translation.override("en"):
        yield


def subjects(user):
    return [n.kind for n in Notification.objects.filter(user=user)]


class TestQuietHours:
    @pytest.mark.parametrize(
        ("hour", "minute", "quiet"),
        [
            (21, 59, False),
            (22, 0, True),
            (23, 30, True),
            (3, 0, True),
            (6, 59, True),
            (7, 0, False),
        ],
    )
    def test_default_window_runs_22_to_07_dhaka_time(self, hour, minute, quiet):
        assert delivery.in_quiet_hours(at(11, hour, minute)) is quiet

    def test_equal_hours_switch_it_off(self, db):
        system_settings.update({"QUIET_HOURS_START": 8, "QUIET_HOURS_END": 8}, actor=make_admin())
        assert delivery.in_quiet_hours(at(11, 23)) is False

    def test_same_day_window(self, db):
        system_settings.update({"QUIET_HOURS_START": 13, "QUIET_HOURS_END": 15}, actor=make_admin())
        assert delivery.in_quiet_hours(at(11, 14)) is True
        assert delivery.in_quiet_hours(at(11, 16)) is False


class TestRoundReminders:
    def test_round_opened_reaches_students_who_owe_a_form(self, world):
        _profile, user = world.student(contact_email="a@example.com")
        assert schedule.send_round_reminders(at(10, 9, 30)) == 1
        assert subjects(user) == [Kind.ROUND_OPENED]
        assert [m.to for m in mail.outbox] == [["a@example.com"]]
        assert "Mid-term" in mail.outbox[0].subject
        assert "1 form" in mail.outbox[0].body

    def test_a_student_who_submitted_is_never_reminded(self, world):
        done, done_user = world.student(contact_email="done@example.com")
        _owing, owing_user = world.student(contact_email="owing@example.com")
        world.submit(done)
        for now in (at(10, 9, 30), at(14, 12), at(16, 12), at(16, 20, 30)):
            schedule.send_round_reminders(now)
        assert not Notification.objects.filter(user=done_user).exists()
        assert Notification.objects.filter(user=owing_user).exists()
        assert all(m.to == ["owing@example.com"] for m in mail.outbox)
        assert not DeliveryLog.objects.filter(user=done_user).exists()

    def test_one_of_two_forms_submitted_still_reminds_for_the_other(self, world):
        profile, user = world.student(contact_email="a@example.com")
        second = make_offering(make_course(world.department, code="CSE102"), world.semester)
        Enrollment.objects.create(student_profile=profile, offering=second)
        world.submit(profile)
        schedule.send_round_reminders(at(10, 9, 30))
        assert "1 form" in mail.outbox[0].body
        assert Notification.objects.get(user=user).params["pending"] == 1

    def test_a_run_repeated_sends_nothing_new(self, world):
        _profile, user = world.student(contact_email="a@example.com")
        assert schedule.send_round_reminders(at(10, 9, 30)) == 1
        assert schedule.send_round_reminders(at(10, 9, 40)) == 0
        assert Notification.objects.filter(user=user).count() == 1
        assert len(mail.outbox) == 1

    def test_three_days_one_day_and_last_hour(self, world):
        _profile, user = world.student(contact_email="a@example.com")
        # Closes Tuesday 17th 09:00: 72 h before is Saturday 14th 09:00.
        for now in (at(10, 9, 30), at(14, 9, 5), at(16, 9, 5), at(17, 8, 5)):
            schedule.send_round_reminders(now)
        kinds = [n.kind for n in Notification.objects.filter(user=user).order_by("id")]
        assert kinds == [
            Kind.ROUND_OPENED,
            Kind.CLOSING_SOON,
            Kind.CLOSING_SOON,
            Kind.CLOSING_SOON,
        ]
        stages = set(Dispatch.objects.filter(user=user).values_list("stage", flat=True))
        assert stages == {"opened", "h72", "h24", "h1"}
        assert "3 days" in mail.outbox[1].subject
        assert "24 hours" in mail.outbox[2].subject
        assert "1 hour" in mail.outbox[3].subject

    def test_schedule_is_configurable(self, world):
        _profile, user = world.student()
        system_settings.update(
            {"REMINDER_HOURS_BEFORE_CLOSE": "12", "REMINDER_ON_OPEN": False},
            actor=make_admin(),
        )
        assert schedule.send_round_reminders(at(10, 9, 30)) == 0
        assert schedule.send_round_reminders(at(16, 21, 30)) == 1
        assert Notification.objects.get(user=user).params["hours"] == 12

    def test_only_the_latest_missed_moment_is_sent(self, world):
        _profile, user = world.student()
        schedule.send_round_reminders(at(16, 12))
        assert Notification.objects.get(user=user).params["hours"] == 24

    def test_closed_and_upcoming_rounds_send_nothing(self, world):
        world.student()
        assert schedule.send_round_reminders(OPENS - timedelta(hours=1)) == 0
        assert schedule.send_round_reminders(CLOSES + timedelta(hours=1)) == 0

    def test_inactive_round_sends_nothing(self, world):
        world.student()
        FeedbackWindow.objects.update(is_active=False)
        assert schedule.send_round_reminders(at(10, 9, 30)) == 0

    def test_round_scope_is_respected(self, world):
        _profile, user = world.student()
        world.window.departments.add(make_course().department)
        assert schedule.send_round_reminders(at(10, 9, 30)) == 0
        assert not Notification.objects.filter(user=user).exists()


class TestQuietHoursDelivery:
    def test_in_app_is_immediate_and_email_waits_for_morning(self, world):
        _profile, user = world.student(contact_email="a@example.com")
        # The 24-hour moment is Monday 16th 09:00; the run at 23:00 is in quiet hours.
        assert schedule.send_round_reminders(at(10, 23)) == 1
        assert subjects(user) == [Kind.ROUND_OPENED]
        assert mail.outbox == []
        assert not DeliveryLog.objects.filter(channel="email").exists()
        schedule.send_round_reminders(at(11, 3))
        assert mail.outbox == []
        schedule.send_round_reminders(at(11, 7, 10))
        assert [m.to for m in mail.outbox] == [["a@example.com"]]
        assert Notification.objects.filter(user=user).count() == 1

    def test_quiet_hours_hold_texts_too(self, world):
        _profile, _user = world.student(contact_phone="+8801712345678")
        schedule.send_round_reminders(at(10, 23))
        assert outbox.texts == []
        schedule.send_round_reminders(at(11, 8))
        assert len(outbox.texts) == 1
        assert outbox.texts[0].channel == "sms"

    def test_an_expired_reminder_is_not_sent_late(self, world):
        world.student(contact_email="a@example.com")
        schedule.send_round_reminders(at(16, 23))  # last hour is still in the future
        schedule.send_round_reminders(CLOSES + timedelta(minutes=5))
        assert mail.outbox == []


class TestDeliveryLog:
    def test_log_holds_kind_channel_status_and_no_content(self, world):
        _profile, user = world.student(contact_email="secret@example.com")
        schedule.send_round_reminders(at(10, 9, 30))
        rows = DeliveryLog.objects.filter(user=user)
        assert {(r.channel, r.status) for r in rows} == {("in_app", "sent"), ("email", "sent")}
        dump = " ".join(str(v) for r in rows for v in vars(r).values())
        assert "secret@example.com" not in dump
        assert "Mid-term" not in dump

    def test_a_failing_sender_is_logged_and_does_not_stop_the_batch(self, world, monkeypatch):
        _a, first = world.student(contact_email="a@example.com")
        _b, second = world.student(contact_email="b@example.com")

        def explode(*args, **kwargs):
            raise OSError("smtp down")

        monkeypatch.setattr("apps.notifications.senders.send_mail", explode)
        schedule.send_round_reminders(at(10, 9, 30))
        failed = DeliveryLog.objects.filter(status="failed")
        assert failed.count() == 2
        assert {f.detail for f in failed} == {"OSError"}
        assert Notification.objects.filter(user__in=[first, second]).count() == 2

    def test_admin_sees_the_log_and_others_do_not(self, web, world):
        world.student()
        schedule.send_round_reminders(at(10, 9, 30))
        sign_in(web, make_admin())
        assert web.get(reverse("notifications:log")).status_code == 200
        web.logout()
        sign_in(web, world.teacher)
        assert web.get(reverse("notifications:log")).status_code == 403


class TestHodReminders:
    def request(self, world, profile):
        return ReminderRequest.objects.create(
            student_profile=profile, offering=world.offering, window=world.window
        )

    def test_a_queued_reminder_is_delivered_once(self, world):
        profile, user = world.student(contact_email="a@example.com")
        queued = self.request(world, profile)
        assert schedule.process_reminder_requests(at(12, 10)) == 1
        assert schedule.process_reminder_requests(at(12, 10, 5)) == 0
        queued.refresh_from_db()
        assert queued.processed_at is not None
        assert subjects(user) == [Kind.HOD_REMINDER]
        assert len(mail.outbox) == 1
        assert world.course.code in mail.outbox[0].subject

    def test_a_student_who_submitted_since_is_not_reminded(self, world):
        profile, user = world.student(contact_email="a@example.com")
        self.request(world, profile)
        world.submit(profile)
        assert schedule.process_reminder_requests(at(12, 10)) == 0
        assert not Notification.objects.filter(user=user).exists()
        assert ReminderRequest.objects.get().processed_at is not None

    def test_a_closed_round_needs_no_reminder(self, world):
        profile, user = world.student()
        self.request(world, profile)
        assert schedule.process_reminder_requests(CLOSES + timedelta(hours=1)) == 0
        assert not Notification.objects.filter(user=user).exists()

    def test_quiet_hours_keep_the_email_back_but_not_the_notice(self, world):
        profile, user = world.student(contact_email="a@example.com")
        self.request(world, profile)
        assert schedule.process_reminder_requests(at(12, 23, 30)) == 1
        assert subjects(user) == [Kind.HOD_REMINDER]
        assert mail.outbox == []
        skipped = DeliveryLog.objects.get(channel="email")
        assert (skipped.status, skipped.detail) == ("skipped", "quiet_hours")

    def test_head_of_department_action_queues_and_the_task_delivers(
        self, web, django_capture_on_commit_callbacks, world
    ):
        hod = make_hod(world.department)
        profile, user = world.student()
        now = timezone.now()
        FeedbackWindow.objects.update(
            opens_at=now - timedelta(hours=1), closes_at=now + timedelta(days=2)
        )
        sign_in(web, hod)
        with django_capture_on_commit_callbacks(execute=True):
            response = web.post(
                reverse("reports:hod_remind"),
                {
                    "window": world.window.pk,
                    "offering": world.offering.pk,
                    "student": profile.pk,
                },
            )
        assert response.status_code == 302
        assert subjects(user) == [Kind.HOD_REMINDER]


class TestResultNotices:
    def test_nothing_while_the_round_is_open(self, world):
        assert schedule.announce_results(CLOSES - timedelta(minutes=1)) == 0
        assert not Notification.objects.exists()

    def test_teacher_and_head_are_told_once_after_close(self, world):
        hod = make_hod(world.department)
        world.teacher.contact_email = "teacher@example.com"
        world.teacher.save()
        now = CLOSES + timedelta(hours=1)
        assert schedule.announce_results(now) == 2
        assert schedule.announce_results(now + timedelta(minutes=15)) == 0
        assert subjects(world.teacher) == [Kind.RESULTS_AVAILABLE]
        assert subjects(hod) == [Kind.RESULTS_AVAILABLE]
        assert Notification.objects.get(user=hod).url == reverse("accounts:dashboard_hod")
        assert Notification.objects.get(user=world.teacher).url == reverse("reports:overview")
        assert [m.to for m in mail.outbox] == [["teacher@example.com"]]

    def test_students_and_unrelated_teachers_are_not_told(self, world):
        _profile, student = world.student()
        other = claim(make_teacher(make_course().department))
        schedule.announce_results(CLOSES + timedelta(hours=1))
        assert not Notification.objects.filter(user__in=[student, other]).exists()

    def test_held_results_are_announced_when_released(self, world):
        system_settings.update({"RESULTS_VISIBLE": "held"}, actor=make_admin())
        now = CLOSES + timedelta(hours=1)
        assert schedule.announce_results(now) == 0
        system_settings.update({"RESULTS_VISIBLE": "after_close"}, actor=make_admin())
        assert schedule.announce_results(now + timedelta(hours=1)) == 1

    def test_old_rounds_are_not_announced(self, world):
        assert schedule.announce_results(CLOSES + timedelta(days=30)) == 0


class TestBell:
    def make(self, user, kind=Kind.RESULTS_AVAILABLE):
        return Notification.objects.create(
            user=user, kind=kind, params={"round": "Mid-term"}, url="/dashboard/"
        )

    def test_badge_counts_unread_and_the_list_renders_the_text(self, web, world):
        sign_in(web, world.teacher)
        assert web.get(reverse("notifications:badge")).content.strip() == b""
        self.make(world.teacher)
        self.make(world.teacher)
        badge = web.get(reverse("notifications:badge")).content.decode()
        assert "2 unread notifications" in badge
        listing = web.get(reverse("notifications:list")).content.decode()
        assert listing.count("Feedback results are available") == 2

    def test_opening_a_notice_marks_it_read_and_follows_its_link(self, web, world):
        notice = self.make(world.teacher)
        sign_in(web, world.teacher)
        response = web.post(reverse("notifications:open", args=[notice.pk]))
        assert response.status_code == 302
        assert response["Location"] == "/dashboard/"
        notice.refresh_from_db()
        assert notice.read_at is not None
        assert inbox.unread_count(world.teacher) == 0

    def test_someone_elses_notice_is_not_found_and_stays_unread(self, web, world):
        notice = self.make(world.teacher)
        _profile, student = world.student()
        sign_in(web, student)
        assert web.post(reverse("notifications:open", args=[notice.pk])).status_code == 404
        notice.refresh_from_db()
        assert notice.read_at is None

    def test_mark_all_read_only_touches_own_notices(self, web, world):
        mine = self.make(world.teacher)
        _profile, student = world.student()
        theirs = self.make(student)
        sign_in(web, world.teacher)
        assert web.post(reverse("notifications:read_all")).status_code == 200
        mine.refresh_from_db()
        theirs.refresh_from_db()
        assert mine.read_at is not None
        assert theirs.read_at is None

    def test_anonymous_visitors_are_sent_to_log_in(self, web):
        assert web.get(reverse("notifications:badge")).status_code == 302

    def test_list_follows_the_page_language(self, web, world):
        self.make(world.teacher)
        sign_in(web, world.teacher)
        web.defaults["HTTP_ACCEPT_LANGUAGE"] = "bn"
        listing = web.get(reverse("notifications:list")).content.decode()
        assert "Feedback results are available" not in listing
        assert "ফলাফল" in listing

    def test_the_header_loads_the_bell_over_htmx(self, web, world):
        sign_in(web, world.teacher)
        page = web.get(reverse("accounts:dashboard_teacher")).content.decode()
        assert reverse("notifications:badge") in page
        assert reverse("notifications:list") in page


class TestTemplates:
    @pytest.mark.parametrize("kind", Kind.values)
    @pytest.mark.parametrize("language", ["en", "bn"])
    def test_every_built_in_template_renders_in_both_languages(self, db, kind, language):
        with translation.override(language):
            values = delivery.values_from_params(
                {
                    "round": "Mid-term",
                    "course": "CSE101",
                    "pending": 2,
                    "hours": 24,
                    "closes_at": CLOSES.isoformat(),
                },
                "/dashboard/",
            )
            text = messages.render(kind, language, values)
        assert text.subject and text.body
        assert "{" not in text.subject + text.body
        if language == "bn":
            assert any("ঀ" <= c <= "৿" for c in text.body)

    def test_a_student_gets_the_message_in_their_own_language(self, world):
        world.student(contact_email="a@example.com", language="bn")
        schedule.send_round_reminders(at(10, 9, 30))
        assert "Mid-term" in mail.outbox[0].subject
        assert "Feedback round open" not in mail.outbox[0].subject

    def test_the_admins_wording_wins_field_by_field(self, db):
        MessageTemplate.objects.create(kind=Kind.RESULTS_AVAILABLE, subject_en="Results: {round}")
        english = messages.wording(Kind.RESULTS_AVAILABLE, "en")
        assert english.subject == "Results: {round}"
        assert english.body == messages.default_wording(Kind.RESULTS_AVAILABLE, "en").body
        assert messages.wording(Kind.RESULTS_AVAILABLE, "bn") == messages.default_wording(
            Kind.RESULTS_AVAILABLE, "bn"
        )

    def test_unknown_placeholders_are_refused_and_nothing_is_evaluated(self, db):
        with pytest.raises(ValidationError):
            messages.validate_placeholders(Kind.RESULTS_AVAILABLE, "Hi {name}")
        with pytest.raises(ValidationError):
            messages.validate_placeholders(Kind.RESULTS_AVAILABLE, "{closes_at}")
        assert messages.fill("{round.__class__} {round}", {"round": "R"}) == "{round.__class__} R"

    def test_admin_edits_a_template_and_it_is_audited(self, web, db):
        admin = make_admin()
        sign_in(web, admin)
        url = reverse("notifications:template_edit", args=[Kind.RESULTS_AVAILABLE])
        assert web.get(url).status_code == 200
        response = web.post(
            url,
            {"subject_en": "Results: {round}", "body_en": "", "subject_bn": "", "body_bn": ""},
        )
        assert response.status_code == 302
        assert MessageTemplate.objects.get().subject_en == "Results: {round}"
        event = AuditEvent.objects.get(action="notifications.template_changed")
        assert event.metadata == {"template": "results_available", "customised": ["subject_en"]}

    def test_a_bad_placeholder_is_shown_as_a_field_error(self, web, db):
        sign_in(web, make_admin())
        url = reverse("notifications:template_edit", args=[Kind.RESULTS_AVAILABLE])
        response = web.post(
            url, {"subject_en": "Hi {nope}", "body_en": "", "subject_bn": "", "body_bn": ""}
        )
        assert response.status_code == 200
        assert "Unknown placeholder" in response.content.decode()
        assert not MessageTemplate.objects.exists()

    def test_clearing_every_field_restores_the_built_in_text(self, web, db):
        MessageTemplate.objects.create(kind=Kind.RESULTS_AVAILABLE, subject_en="X")
        sign_in(web, make_admin())
        url = reverse("notifications:template_edit", args=[Kind.RESULTS_AVAILABLE])
        web.post(url, {"subject_en": "", "body_en": "", "subject_bn": "", "body_bn": ""})
        assert not MessageTemplate.objects.exists()

    def test_unknown_kind_is_not_found(self, web, db):
        sign_in(web, make_admin())
        assert web.get(reverse("notifications:template_edit", args=["nope"])).status_code == 404

    def test_test_send_reaches_the_admin_in_the_chosen_language_even_in_quiet_hours(self, web, db):
        admin = make_admin(contact_email="admin@example.com", language="en")
        sign_in(web, admin)
        url = reverse("notifications:template_test", args=[Kind.CLOSING_SOON])
        web.post(url, {"language": "bn"})
        assert [m.to for m in mail.outbox] == [["admin@example.com"]]
        assert "24" in mail.outbox[0].subject
        assert subjects(admin) == [Kind.CLOSING_SOON]
        assert "hour" not in mail.outbox[0].subject

    def test_test_send_without_an_email_still_gives_the_in_app_notice(self, db):
        admin = make_admin()
        assert editor.send_test(Kind.ROUND_OPENED, "en", admin) == {"in_app"}
        assert mail.outbox == []

    def test_only_the_admin_may_edit_or_test(self, web, world):
        sign_in(web, world.teacher)
        edit = reverse("notifications:template_edit", args=[Kind.ROUND_OPENED])
        test = reverse("notifications:template_test", args=[Kind.ROUND_OPENED])
        assert web.get(reverse("notifications:template_list")).status_code == 403
        assert web.get(edit).status_code == 403
        assert web.post(test, {"language": "en"}).status_code == 403


class TestSettingsAndCommand:
    def test_default_schedule_is_three_days_one_day_last_hour(self, db):
        assert system_settings.get("REMINDER_HOURS_BEFORE_CLOSE") == [72, 24, 1]

    def test_quiet_hours_are_bounded(self, db):
        with pytest.raises(ValidationError):
            system_settings.update({"QUIET_HOURS_START": 24}, actor=make_admin())

    def test_command_runs_the_jobs(self, db, capsys):
        from django.core.management import call_command

        call_command("send_notifications")
        assert "round reminders: 0" in capsys.readouterr().out
