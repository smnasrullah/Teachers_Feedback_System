"""The demo data, seeded once per module and rolled back afterwards, and sample URL arguments.

Every test still runs in its own savepoint (pytest-django's ``db``), so a POST in one test never
leaks into the next.
"""

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.db import transaction
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver
from django.utils import timezone

from apps.academics.models import CourseOffering, Semester
from apps.academics.screens import SCREENS
from apps.academics.services.importers import IMPORTERS
from apps.accounts.models import IdRegistry, IdType, StudentProfile, User, registry_index
from apps.core.services.demo import constants as demo
from apps.enrollment.models import Enrollment
from apps.feedback.models import (
    Answer,
    FeedbackWindow,
    FilterTerm,
    ModerationStatus,
    Question,
    QuestionCategory,
)
from apps.notifications.models import Kind, Notification
from tests.factories import sign_in

# The demo semesters have fixed dates: run inside them (see tests/test_demo_seed.py).
DEMO_NOW = datetime(2026, 10, 27, 12, 0, tzinfo=ZoneInfo("Asia/Dhaka"))
ROLES = ("anonymous", demo.STUDENT, demo.TEACHER, demo.HOD, demo.ADMIN)
# Django's own admin screens take a raw object path; the crawl visits their index only.
SKIPPED_PATTERNS = {"admin:view_on_site", "admin:?", "admin:app_list", "media"}


@pytest.fixture(scope="module")
def demo_db(django_db_setup, django_db_blocker):
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(timezone, "now", lambda: DEMO_NOW)
        with django_db_blocker.unblock(), transaction.atomic():
            from django.conf import settings

            debug, module = settings.DEBUG, settings.SETTINGS_MODULE
            settings.DEBUG, settings.SETTINGS_MODULE = True, "config.settings.dev"
            try:
                call_command("seed_demo", "--password", "Crawl-Pass-2026!x", verbosity=0)
            finally:
                settings.DEBUG, settings.SETTINGS_MODULE = debug, module
            yield
            transaction.set_rollback(True)


@pytest.fixture
def seeded(demo_db, db, monkeypatch):
    monkeypatch.setattr(timezone, "now", lambda: DEMO_NOW)


def client_for(role: str, language: str = "en", **kwargs) -> Client:
    client = Client(HTTP_ACCEPT_LANGUAGE=language, **kwargs)
    if role != "anonymous":
        sign_in(client, User.objects.get(username=role))
    return client


@dataclass(frozen=True)
class Route:
    name: str
    pattern: str


def all_routes() -> list[Route]:
    def walk(resolver, prefix="", namespace=None):
        for entry in resolver.url_patterns:
            if isinstance(entry, URLResolver):
                inner = ":".join(part for part in (namespace, entry.namespace) if part) or None
                yield from walk(entry, prefix + str(entry.pattern), inner)
            elif isinstance(entry, URLPattern):
                name = f"{namespace}:{entry.name or '?'}" if namespace else entry.name or "?"
                if name not in SKIPPED_PATTERNS:
                    yield Route(name, prefix + str(entry.pattern))

    return list(walk(get_resolver()))


def window(name: str) -> FeedbackWindow:
    return FeedbackWindow.objects.get(name=name)


def offering(semester: tuple[str, int], code: str) -> CourseOffering:
    season, year = semester
    return CourseOffering.objects.get(
        semester__season=season, semester__year=year, course__code=code
    )


def registry(external_id: str) -> IdRegistry:
    return IdRegistry.objects.get(external_id_index=registry_index(external_id))


def _comment_question(target: CourseOffering) -> Question:
    answered = Question.objects.filter(answers__response__offering=target, question_type="text")
    return answered.distinct().first() or Question.objects.filter(question_type="text").first()


def _first(queryset):
    row = queryset.order_by("pk").first()
    assert row is not None, f"the demo data has no {queryset.model.__name__}"
    return row


def _entities() -> list[dict]:
    return [
        {"entity": key, "pk": _first(screen.model.objects.all()).pk}
        for key, screen in SCREENS.items()
    ]


def _form() -> dict:
    return {
        "window_id": window(demo.SUMMER_ROUND).pk,
        "offering_id": offering(demo.SUMMER, "CSE-2102").pk,
    }


def _report() -> dict:
    taught = offering(demo.SUMMER, demo.DEMO_TEACHER_COURSES[0])
    return {"offering_id": taught.pk, "window_id": window(demo.SUMMER_EARLY_ROUND).pk}


def _student() -> StudentProfile:
    return StudentProfile.objects.get(registry=registry(demo.CSE_STUDENT_IDS[1]))


def _user(username: str) -> dict:
    return {"pk": User.objects.get(username=username).pk}


def _formats(**kwargs) -> list[dict]:
    return [{**kwargs, "fmt": fmt} for fmt in ("csv", "xlsx")]


SAMPLES = {
    "feedback:form": lambda user: [_form()],
    "feedback:draft": lambda user: [_form()],
    "feedback:done": lambda user: [_form()],
    "feedback:precheck": lambda user: [
        {**_form(), "question_id": _comment_question(offering(demo.SUMMER, "CSE-2102")).pk}
    ],
    "reports:course": lambda user: [_report()],
    "reports:print": lambda user: [_report()],
    "reports:note": lambda user: [_report()],
    "reports:report_comment": lambda user: [_report()],
    "reports:comments": lambda user: [
        {
            **_report(),
            "question_id": _comment_question(
                offering(demo.SUMMER, demo.DEMO_TEACHER_COURSES[0])
            ).pk,
        }
    ],
    "reports:export_course": lambda user: _formats(**_report()),
    "reports:export_department": lambda user: _formats(),
    "reports:export_pending": lambda user: _formats(),
    "reports:export_university": lambda user: _formats(),
    "accounts:registry_create": lambda user: [{"id_type": value} for value in IdType.values],
    "accounts:registry_edit": lambda user: [{"pk": _student().registry_id}],
    "accounts:registry_hod": lambda user: [{"pk": registry(demo.TEACHERS[1].external_id).pk}],
    "accounts:user_detail": lambda user: [_user(demo.STUDENT)],
    "accounts:user_role": lambda user: [_user(demo.TEACHER)],
    "accounts:user_reset_access": lambda user: [_user(demo.STUDENT)],
    "academics:import_upload": lambda user: [{"kind": key} for key in IMPORTERS],
    "academics:import_apply": lambda user: [{"kind": key} for key in IMPORTERS],
    "academics:import_template": lambda user: [{"kind": key} for key in IMPORTERS],
    "academics:grade_sheet": lambda user: [{"pk": offering(demo.WINTER, "CSE-1201").pk}],
    "academics:promotion_confirm": lambda user: [{"semester_pk": semester(demo.WINTER).pk}],
    "academics:promotion_override": lambda user: [
        {"semester_pk": semester(demo.WINTER).pk, "student_pk": _student().pk}
    ],
    "academics:list": lambda user: [{"entity": key} for key in SCREENS],
    "academics:create": lambda user: [{"entity": key} for key in SCREENS],
    "academics:edit": lambda user: _entities(),
    "academics:delete": lambda user: _entities(),
    "enrollment:remove": lambda user: [{"pk": _first(Enrollment.objects.all()).pk}],
    "feedback:question_edit": lambda user: [{"pk": _first(Question.objects.all()).pk}],
    "feedback:question_duplicate": lambda user: [{"pk": _first(Question.objects.all()).pk}],
    "feedback:question_toggle": lambda user: [{"pk": _first(Question.objects.all()).pk}],
    "feedback:category_edit": lambda user: [{"pk": _first(QuestionCategory.objects.all()).pk}],
    "feedback:filter_term_delete": lambda user: [
        {"pk": row.pk} for row in FilterTerm.objects.order_by("pk")[:1]
    ],
    "feedback:moderation_decide": lambda user: [
        {"pk": row.pk}
        for row in Answer.objects.filter(flagged=True, moderation=ModerationStatus.UNREVIEWED)[:1]
    ],
    "feedback:window_edit": lambda user: [{"pk": window(demo.SUMMER_EARLY_ROUND).pk}],
    "feedback:window_preview": lambda user: [{"pk": window(demo.SUMMER_ROUND).pk}],
    "notifications:open": lambda user: [
        {"pk": row.pk} for row in Notification.objects.filter(user=user).order_by("pk")[:1]
    ],
    "notifications:template_edit": lambda user: [{"kind": Kind.values[0]}],
    "notifications:template_test": lambda user: [{"kind": Kind.values[0]}],
}


def sample_kwargs(name: str, user: User | None) -> list[dict]:
    """Valid arguments for the route, from the side of the demo student/teacher/CSE head.

    One route can expand to several (an entity per academic screen, one export format each);
    an empty list means the demo data has nothing to point the route at for this user.
    """
    builder = SAMPLES.get(name)
    return builder(user) if builder else [{}]


def semester(key: tuple[str, int]) -> Semester:
    season, year = key
    return Semester.objects.get(season=season, year=year)
