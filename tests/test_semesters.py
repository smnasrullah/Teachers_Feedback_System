"""Winter/Summer semesters: computed name and status, admin-only date edits with their rules,
the "next semester" suggestion, the promotion gate, the dashboard badge and the migration."""

from datetime import UTC, date, datetime, timedelta

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.urls import reverse
from django.utils import timezone, translation

from apps.academics.models import Season, Semester, SemesterStatus
from apps.academics.services import promotion, semesters
from apps.auditlog.models import AuditEvent
from apps.feedback.models import FeedbackWindow
from tests.factories import claim, make_admin, make_hod, make_student, make_teacher, sign_in
from tests.test_academics import make_semester
from tests.test_results_promotion import World

pytestmark = pytest.mark.django_db

SUMMER_START, SUMMER_END = date(2026, 7, 1), date(2027, 1, 30)
DHAKA_LAST_MINUTE = datetime(2027, 1, 30, 17, 59, tzinfo=UTC)  # 30 Jan 23:59 in Dhaka
DHAKA_NEXT_DAY = datetime(2027, 1, 30, 18, 0, tzinfo=UTC)  # 31 Jan 00:00 in Dhaka


@pytest.fixture(autouse=True)
def english():
    with translation.override("en"):
        yield


@pytest.fixture
def admin_client(client):
    client.defaults["HTTP_ACCEPT_LANGUAGE"] = "en"
    sign_in(client, make_admin())
    return client


@pytest.fixture
def summer():
    return make_semester(
        season=Season.SUMMER, year=2026, start_date=SUMMER_START, end_date=SUMMER_END
    )


def freeze(monkeypatch, moment: datetime) -> None:
    monkeypatch.setattr(timezone, "now", lambda: moment)


def edit_url(semester) -> str:
    return reverse("academics:edit", args=["semesters", semester.pk])


def form_data(semester, **changes) -> dict:
    data = {
        "season": semester.season,
        "year": str(semester.year),
        "start_date": semester.start_date.isoformat(),
        "end_date": semester.end_date.isoformat(),
    }
    return {**data, **changes}


def make_round(semester, opens: date, closes: date, name="Mid-term") -> FeedbackWindow:
    zone = timezone.get_default_timezone()
    return FeedbackWindow.objects.create(
        semester=semester,
        name=name,
        opens_at=datetime(opens.year, opens.month, opens.day, 9, tzinfo=zone),
        closes_at=datetime(closes.year, closes.month, closes.day, 17, tzinfo=zone),
    )


class TestNameAndStatus:
    def test_name_is_computed_in_both_languages(self, summer):
        assert summer.name == "Summer 2026"
        with translation.override("bn"):
            assert summer.name == "সামার ২০২৬"
            assert Semester(season=Season.WINTER, year=2027).name == "উইন্টার ২০২৭"

    def test_the_last_minute_of_the_end_day_in_dhaka_is_still_ongoing(self, summer, monkeypatch):
        freeze(monkeypatch, DHAKA_LAST_MINUTE)
        assert summer.status(semesters.today()) == SemesterStatus.ONGOING
        assert semesters.current_semester() == summer

    def test_the_next_day_in_dhaka_it_has_ended(self, summer, monkeypatch):
        freeze(monkeypatch, DHAKA_NEXT_DAY)
        assert summer.status(semesters.today()) == SemesterStatus.ENDED
        assert semesters.current_semester() is None

    def test_before_the_start_it_is_upcoming(self, summer):
        assert summer.status(date(2026, 6, 30)) == SemesterStatus.UPCOMING
        assert summer.status(SUMMER_START) == SemesterStatus.ONGOING


class TestAdminScreens:
    def test_admin_edits_the_dates_and_it_is_audited(self, admin_client, summer):
        response = admin_client.post(
            edit_url(summer), form_data(summer, start_date="2026-07-15", end_date="2027-02-10")
        )
        assert response.status_code == 302
        summer.refresh_from_db()
        assert (summer.start_date, summer.end_date) == (date(2026, 7, 15), date(2027, 2, 10))
        event = AuditEvent.objects.get(action="academics.semester_updated")
        assert event.object_id == str(summer.pk)
        assert event.metadata == {
            "entity": "semesters",
            "start_date": ["2026-07-01", "2026-07-15"],
            "end_date": ["2027-01-30", "2027-02-10"],
        }

    def test_creating_is_audited_with_the_dates(self, admin_client):
        data = {
            "season": "winter",
            "year": "2027",
            "start_date": "2027-02-01",
            "end_date": "2027-06-30",
        }
        response = admin_client.post(reverse("academics:create", args=["semesters"]), data)
        assert response.status_code == 302
        event = AuditEvent.objects.get(action="academics.semester_created")
        assert event.metadata["start_date"] == "2027-02-01"
        assert Semester.objects.get().name == "Winter 2027"

    def test_non_admins_get_403(self, client, summer):
        urls = [
            reverse("academics:list", args=["semesters"]),
            reverse("academics:create", args=["semesters"]),
            edit_url(summer),
        ]
        for user in (claim(make_student()), claim(make_teacher()), make_hod()):
            sign_in(client, user)
            for url in urls:
                assert client.get(url).status_code == 403
            assert client.post(edit_url(summer), form_data(summer)).status_code == 403
        summer.refresh_from_db()
        assert summer.end_date == SUMMER_END

    def test_overlapping_dates_are_rejected(self, admin_client, summer):
        data = {
            "season": "winter",
            "year": "2027",
            "start_date": "2027-01-15",
            "end_date": "2027-06-30",
        }
        response = admin_client.post(reverse("academics:create", args=["semesters"]), data)
        assert response.status_code == 200
        assert "These dates overlap Summer 2026" in response.content.decode()
        assert Semester.objects.count() == 1

    def test_shrinking_below_a_round_is_blocked_and_names_it(self, admin_client, summer):
        make_round(summer, date(2027, 1, 10), date(2027, 1, 25), name="End-of-term")
        response = admin_client.post(edit_url(summer), form_data(summer, end_date="2027-01-20"))
        assert response.status_code == 200
        body = response.content.decode()
        assert "End-of-term" in body and "outside the semester" in body
        summer.refresh_from_db()
        assert summer.end_date == SUMMER_END
        assert not AuditEvent.objects.filter(action="academics.semester_updated").exists()

    def test_the_service_checks_the_rules_again_when_saving(self, summer):
        make_round(summer, date(2026, 7, 2), date(2026, 7, 9))
        with pytest.raises(Exception, match="outside the semester"):
            semesters.validate_dates(summer, date(2026, 7, 5), SUMMER_END)

    def test_the_bangla_error_names_the_blocking_round(self, client, summer):
        client.defaults["HTTP_ACCEPT_LANGUAGE"] = "bn"
        sign_in(client, make_admin())
        make_round(summer, date(2027, 1, 10), date(2027, 1, 25), name="End-of-term")
        with translation.override("bn"):
            response = client.post(edit_url(summer), form_data(summer, end_date="2027-01-20"))
        body = response.content.decode()
        assert "End-of-term" in body and "সেমিস্টারের বাইরে" in body

    def test_next_semester_is_suggested_in_turn(self, admin_client, summer):
        url = reverse("academics:create", args=["semesters"])
        form = admin_client.get(url, {"suggested": "1"}).context["form"]
        assert (form.initial["season"], form.initial["year"]) == (Season.WINTER, 2027)
        assert not form.initial.get("start_date")
        assert semesters.following(Season.WINTER, 2027) == (Season.SUMMER, 2027)
        listing = admin_client.get(reverse("academics:list", args=["semesters"])).content.decode()
        assert "Create next semester" in listing and "?suggested=1" in listing


class TestPromotionGate:
    def test_promotion_waits_for_the_end_date_and_follows_it(self, monkeypatch):
        world = World()
        admin = make_admin()
        world.graded("A A A")
        world.s1.end_date = semesters.today() + timedelta(days=5)
        world.s1.save()
        with pytest.raises(Exception, match="can be applied after it ends"):
            promotion.apply(promotion.preview(world.s1), actor=admin)
        world.s1.end_date = semesters.today() - timedelta(days=1)
        world.s1.save()
        assert promotion.apply(promotion.preview(world.s1), actor=admin) == 1


class TestDashboards:
    def test_every_dashboard_shows_the_semester_and_its_end(self, client, summer, monkeypatch):
        freeze(monkeypatch, datetime(2026, 10, 27, 6, tzinfo=UTC))
        client.defaults["HTTP_ACCEPT_LANGUAGE"] = "en"
        pages = {
            make_admin(): "accounts:dashboard_admin",
            make_hod(): "accounts:dashboard_hod",
            claim(make_teacher()): "reports:overview",
            claim(make_student()): "accounts:dashboard_student",
        }
        for user, name in pages.items():
            sign_in(client, user)
            body = client.get(reverse(name), follow=True).content.decode()
            assert "Summer 2026 · ends 30 Jan 2027" in body, name

    def test_bangla_uses_bangla_digits(self, client, summer, monkeypatch):
        freeze(monkeypatch, datetime(2026, 10, 27, 6, tzinfo=UTC))
        client.defaults["HTTP_ACCEPT_LANGUAGE"] = "bn"
        sign_in(client, claim(make_student()))
        with translation.override("bn"):
            body = client.get(reverse("accounts:dashboard_student")).content.decode()
        assert "সামার ২০২৬" in body and "৩০" in body and "২০২৭" in body


@pytest.mark.django_db(transaction=True)
def test_the_migration_converts_existing_semesters():
    before, after = (
        [("academics", "0004_default_grade_scale")],
        [("academics", "0007_semester_season_year_final")],
    )
    executor = MigrationExecutor(connection)
    executor.migrate(before)
    old = executor.loader.project_state(before).apps.get_model("academics", "Semester")
    rows = {
        "Spring 2026": (date(2026, 1, 1), date(2026, 6, 30), False),
        "Fall 2025": (date(2025, 7, 1), date(2025, 12, 31), False),
        "Summer 2026": (date(2026, 7, 1), date(2027, 1, 30), True),
        "Autumn 2026": (date(2026, 8, 1), date(2026, 12, 31), False),
        "উইন্টার ২০২৪": (date(2024, 1, 1), date(2024, 6, 30), False),
    }
    ids = {
        name: old.objects.create(name=name, start_date=start, end_date=end, is_current=current).pk
        for name, (start, end, current) in rows.items()
    }
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(after)
    new = executor.loader.project_state(after).apps.get_model("academics", "Semester")
    found = {name: new.objects.get(pk=pk) for name, pk in ids.items()}
    assert {name: (s.season, s.year) for name, s in found.items()} == {
        "Spring 2026": ("winter", 2026),
        "Fall 2025": ("summer", 2025),
        "Summer 2026": ("summer", 2026),
        "Autumn 2026": ("winter", 2027),  # Summer 2026 is taken: the next season in turn
        "উইন্টার ২০২৪": ("winter", 2024),
    }
    assert all(
        (s.start_date, s.end_date) == rows[name][:2] for name, s in found.items()
    )  # no date is lost
