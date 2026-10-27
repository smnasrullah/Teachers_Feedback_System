"""The development demo data: safe to run twice, dev-only, and consistent with the rules."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import CourseOffering
from apps.academics.screens import SCREENS
from apps.academics.services import semesters
from apps.accounts.models import IdRegistry, StudentProfile, User
from apps.accounts.services import twofactor
from apps.analytics import services as analytics
from apps.auditlog.models import AuditEvent
from apps.core.services.demo import constants as demo
from apps.feedback.models import (
    Answer,
    FeedbackResponse,
    FeedbackWindow,
    Question,
    QuestionCategory,
)
from apps.feedback.services import anonymity, portal
from apps.reports.services import teacher as teacher_report
from tests.factories import claim, make_admin, make_student, sign_in
from tests.test_feedback_core import ANONYMOUS, identifying_path

PASSWORD = "Demo-Pass-2026!x"
DEMO_APPS = {"academics", "accounts", "enrollment", "feedback", "reports", "notifications"}
# The demo semesters have fixed dates (Summer 2026 ends on 30 January 2027): run inside them.
DEMO_NOW = datetime(2026, 10, 27, 12, 0, tzinfo=ZoneInfo("Asia/Dhaka"))


@pytest.fixture(autouse=True)
def demo_clock(monkeypatch):
    monkeypatch.setattr(timezone, "now", lambda: DEMO_NOW)


def seed(settings, *args):
    """Run ``seed_demo`` the way the owner does (dev settings), then go back to test settings."""
    settings.DEBUG = True
    settings.SETTINGS_MODULE = "config.settings.dev"  # set last: each override resets it
    try:
        call_command("seed_demo", *args)
    finally:
        settings.DEBUG = False
        settings.SETTINGS_MODULE = "config.settings.test"


@pytest.fixture
def seeded(db, settings):
    seed(settings, "--password", PASSWORD)


def snapshot() -> dict[str, int]:
    counts = {
        model.__name__: model.objects.count()
        for model in apps.get_models()
        if model._meta.app_label in DEMO_APPS
    }
    return {**counts, "AuditEvent": AuditEvent.objects.count()}


def signed_in(username: str) -> Client:
    client = Client(HTTP_ACCEPT_LANGUAGE="en")
    sign_in(client, User.objects.get(username=username))
    return client


def offering(semester: tuple[str, int], code: str) -> CourseOffering:
    season, year = semester
    return CourseOffering.objects.get(
        semester__season=season, semester__year=year, course__code=code
    )


def round_named(name: str) -> FeedbackWindow:
    return FeedbackWindow.objects.get(name=name)


# --- the command ------------------------------------------------------------------------------


def test_seeding_twice_changes_nothing(seeded, settings):
    first = snapshot()
    seed(settings)
    assert snapshot() == first


@pytest.mark.parametrize(
    ("module", "debug"),
    [
        ("config.settings.test", True),
        ("config.settings.prod", False),
        ("config.settings.dev", False),
    ],
)
def test_it_refuses_to_run_outside_development(db, settings, module, debug):
    settings.DEBUG = debug
    settings.SETTINGS_MODULE = module
    for args in ((), ("--reset",)):
        with pytest.raises(CommandError, match="DEBUG"):
            call_command("seed_demo", *args)
    assert not User.objects.exists()


def test_the_password_and_keys_are_printed_but_never_stored(db, settings, capsys):
    seed(settings, "--password", PASSWORD)
    out = capsys.readouterr().out
    assert PASSWORD in out
    for user in User.objects.filter(username__in=demo.USERNAMES):
        assert user.totp_enabled
        assert twofactor.manual_key(user.totp_secret) in out
    stored = json.dumps(list(AuditEvent.objects.values_list("metadata", flat=True)))
    assert PASSWORD not in stored
    assert not any(external_id in stored for external_id in demo.all_registry_ids())


def test_a_random_password_is_made_when_none_is_given(db, settings, capsys, monkeypatch):
    monkeypatch.delenv("DEMO_PASSWORD", raising=False)
    seed(settings)
    out = capsys.readouterr().out
    assert "generated, shown only now" in out
    seed(settings)
    assert "Passwords are unchanged" in capsys.readouterr().out


def test_the_spare_pairs_work_for_a_real_sign_up(seeded, settings, capsys):
    seed(settings, "--reset")
    seed(settings, "--password", PASSWORD)
    lines = [line.split() for line in capsys.readouterr().out.splitlines() if "DEMO-S01" in line]
    assert [line[0] for line in lines] == list(demo.CSE_STUDENT_IDS[-2:])
    web = Client(HTTP_ACCEPT_LANGUAGE="en")
    external_id, code = lines[0]
    web.post(reverse("accounts:signup"), {"registry_id": external_id, "activation_code": code})
    assert web.session["signup"]["registry"]


def test_reset_removes_only_the_demo_objects(db, settings):
    real_admin = make_admin(PASSWORD)
    real_profile = make_student()
    real_user = claim(real_profile)
    seed(settings, "--password", PASSWORD)
    assert IdRegistry.objects.count() > 1
    seed(settings, "--reset")
    assert not User.objects.filter(username__in=demo.USERNAMES).exists()
    assert IdRegistry.objects.count() == 1
    assert not FeedbackResponse.objects.exists()
    assert not CourseOffering.objects.exists()
    assert set(User.objects.all()) == {real_admin, real_user}
    assert StudentProfile.objects.get().pk == real_profile.pk


# --- what each account sees ------------------------------------------------------------------


def test_the_student_sees_only_enrolled_courses_and_no_student_id(seeded):
    client = signed_in(demo.STUDENT)
    html = client.get(reverse("accounts:dashboard_student")).content.decode()
    for code in demo.SUMMER_COURSES:
        assert code in html
    for code in demo.WINTER_EEE_COURSES:
        assert code not in html
    for external_id in demo.all_registry_ids():
        assert external_id not in html
    for name in (*demo.CSE_STUDENT_NAMES[1:], *demo.EEE_STUDENT_NAMES):
        assert name not in html


def test_the_student_has_two_sealed_and_four_pending_forms(seeded):
    profile = User.objects.get(username=demo.STUDENT).student_profile
    entries = portal.build_dashboard(profile, timezone.now()).entries
    states = [entry.state for entry in entries]
    assert states.count(portal.CourseState.SUBMITTED) == len(demo.DEMO_STUDENT_SEALED)
    assert states.count(portal.CourseState.PENDING) == (
        len(demo.SUMMER_COURSES) - len(demo.DEMO_STUDENT_SEALED)
    )
    assert profile.level_term.name == demo.L2T1
    assert profile.enrollments.filter(offering__semester__in=semesters.ongoing()).count() == len(
        demo.SUMMER_COURSES
    )


def test_the_student_cannot_open_a_course_they_are_not_enrolled_in(seeded):
    client = signed_in(demo.STUDENT)
    eee = offering(demo.WINTER, "EEE-2101")
    for window in (round_named(demo.SUMMER_ROUND), round_named(demo.WINTER_ROUND)):
        url = reverse("feedback:form", args=[window.pk, eee.pk])
        assert client.get(url).status_code == 404
    own = offering(demo.SUMMER, "CSE-2102")
    assert (
        client.get(reverse("feedback:form", args=[round_named(demo.SUMMER_ROUND).pk, own.pk]))
    ).status_code == 200


def test_the_hod_cannot_open_an_eee_report_but_sees_the_cse_pending_list(seeded):
    client = signed_in(demo.HOD)
    closed = round_named(demo.WINTER_ROUND)
    eee = offering(demo.WINTER, "EEE-2101")
    assert client.get(reverse("reports:course", args=[eee.pk, closed.pk])).status_code == 403
    cse = offering(demo.WINTER, "CSE-1201")
    assert client.get(reverse("reports:course", args=[cse.pk, closed.pk])).status_code == 200
    html = client.get(reverse("reports:hod_pending")).content.decode()
    assert any(f"DEMO-S0{n:02d}" in html for n in range(2, 14))
    assert not any(external_id in html for external_id in demo.EEE_STUDENT_IDS)
    assert "DEMO-S001" in html


def test_the_admin_opens_every_admin_screen(seeded):
    client = signed_in(demo.ADMIN)
    window = round_named(demo.WINTER_ROUND)
    sheet = offering(demo.WINTER, "CSE-1201")
    names = [
        "accounts:dashboard_admin",
        "accounts:registry_list",
        "accounts:user_list",
        "academics:assign_teachers",
        "academics:import_index",
        "academics:results",
        "academics:promotion",
        "academics:promotion_rule",
        "enrollment:list",
        "enrollment:group",
        "enrollment:missing",
        "feedback:questions",
        "feedback:question_create",
        "feedback:categories",
        "feedback:filter_terms",
        "feedback:moderation",
        "feedback:windows",
        "feedback:window_create",
        "auditlog:log",
        "notifications:template_list",
        "notifications:log",
        "reports:analytics",
        "core:settings",
    ]
    urls = [reverse(name) for name in names]
    urls += [reverse("academics:list", args=[key]) for key in SCREENS]
    urls += [
        reverse("academics:grade_sheet", args=[sheet.pk]),
        reverse("feedback:window_edit", args=[window.pk]),
        reverse("reports:course", args=[sheet.pk, window.pk]),
    ]
    assert {url: client.get(url).status_code for url in urls} == dict.fromkeys(urls, 200)


def test_the_promotion_preview_shows_every_outcome(seeded):
    client = signed_in(demo.ADMIN)
    winter = round_named(demo.WINTER_ROUND).semester
    html = client.get(reverse("academics:promotion"), {"semester": winter.pk}).content.decode()
    for label in ("Promote", "Retain", "Promote with retakes", "Graduate"):
        assert label in html


def test_the_login_page_lists_the_demo_usernames_only_in_development(db, settings):
    web = Client(HTTP_ACCEPT_LANGUAGE="en")
    settings.DEBUG = True
    html = web.get(reverse("accounts:login")).content.decode()
    assert all(username in html for username in demo.USERNAMES)
    assert "sign in with password only" in html
    settings.DEBUG = False
    html = web.get(reverse("accounts:login")).content.decode()
    assert not any(username in html for username in demo.USERNAMES)


def test_every_demo_account_can_log_in_with_its_authenticator(seeded):
    for username in demo.USERNAMES:
        web = Client(HTTP_ACCEPT_LANGUAGE="en")
        user = User.objects.get(username=username)
        step = web.post(reverse("accounts:login"), {"username": username, "password": PASSWORD})
        assert step.status_code == 302
        code = twofactor.current_code(user.totp_secret)
        done = web.post(reverse("accounts:login_second_factor"), {"code": code})
        assert done.status_code == 302
        assert web.get(done["Location"]).status_code == 200


# --- the feedback data -----------------------------------------------------------------------


def test_the_closed_round_is_visible_where_enough_students_answered(seeded):
    closed = round_named(demo.WINTER_ROUND)
    admin = User.objects.get(username=demo.ADMIN)
    now = timezone.now()
    assert closed.has_closed(now)
    for code in demo.WINTER_CSE_COURSES:
        target = offering(demo.WINTER, code)
        count = FeedbackResponse.objects.filter(offering=target, window=closed).count()
        assert count >= 9
        summary = teacher_report.summarize(target, closed, admin, now)
        assert summary.average is not None


def test_the_small_eee_class_stays_below_the_minimum(seeded):
    closed = round_named(demo.WINTER_ROUND)
    admin = User.objects.get(username=demo.ADMIN)
    now = timezone.now()
    for code in demo.WINTER_EEE_COURSES:
        target = offering(demo.WINTER, code)
        count = FeedbackResponse.objects.filter(offering=target, window=closed).count()
        assert 0 < count < anonymity.min_responses()
        summary = teacher_report.summarize(target, closed, admin, now)
        assert summary.average is None
        assert summary.notice == analytics.NOT_ENOUGH_MESSAGE
    client = signed_in(demo.ADMIN)
    eee = offering(demo.WINTER, "EEE-2101")
    html = client.get(reverse("reports:course", args=[eee.pk, closed.pk])).content.decode()
    assert "Not enough responses to show this." in html


def test_the_open_round_shows_no_results_yet(seeded):
    open_round = round_named(demo.SUMMER_ROUND)
    assert FeedbackResponse.objects.filter(window=open_round).exists()
    assert not anonymity.results_visible(open_round)


def test_comments_with_abusive_words_wait_in_the_moderation_queue(seeded):
    assert Answer.objects.filter(flagged=True).awaiting_review().count() >= 3
    html = signed_in(demo.ADMIN).get(reverse("feedback:moderation")).content.decode()
    assert "idiot" not in html


def test_the_bank_has_six_categories_and_every_type(seeded):
    assert QuestionCategory.objects.count() >= 6
    kinds = set(Question.objects.values_list("question_type", flat=True))
    assert {"rating", "choice", "yesno", "text"} <= kinds
    assert {"theory", "lab"} <= set(Question.objects.values_list("applies_to", flat=True))


def test_the_anonymity_structure_still_holds_after_seeding(seeded):
    assert identifying_path(ANONYMOUS) is None
    answer = Answer.objects.first()
    assert {field.name for field in answer._meta.concrete_fields}.isdisjoint(
        {"created_at", "updated_at", "ip", "user"}
    )
