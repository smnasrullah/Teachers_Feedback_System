"""Object-level checks: a valid id that belongs to someone else is refused, never shown."""

import pytest
from django.urls import reverse

from apps.academics.models import Department
from apps.core.services.demo import constants as demo
from apps.notifications.models import Notification
from tests.qa.conftest import client_for, offering, window

REFUSED = {403, 404}


def _foreign_report(code: str, semester=demo.SUMMER, round_name=demo.SUMMER_EARLY_ROUND):
    return offering(semester, code), window(round_name)


@pytest.mark.parametrize(
    "name", ["reports:course", "reports:print", "reports:export_course", "reports:comments"]
)
def test_a_teacher_cannot_open_a_colleagues_course(seeded, name):
    """CSE-2103 belongs to another CSE teacher; the demo teacher is not its head."""
    target, closed = _foreign_report("CSE-2103")
    kwargs = {"offering_id": target.pk, "window_id": closed.pk}
    if name == "reports:export_course":
        kwargs["fmt"] = "csv"
    if name == "reports:comments":
        kwargs["question_id"] = 1
    response = client_for(demo.TEACHER).get(reverse(name, kwargs=kwargs))

    assert response.status_code in REFUSED
    assert target.course.title.encode() not in response.content


@pytest.mark.parametrize("name", ["reports:note", "reports:report_comment"])
def test_a_teacher_cannot_write_on_a_colleagues_course(seeded, name):
    target, closed = _foreign_report("CSE-2103")
    url = reverse(name, kwargs={"offering_id": target.pk, "window_id": closed.pk})

    response = client_for(demo.TEACHER).post(url, {"text": "x", "answer": "x", "reason": "x"})

    assert response.status_code in REFUSED


@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_a_head_cannot_export_another_departments_course(seeded, fmt):
    target, closed = _foreign_report("EEE-2101", demo.WINTER, demo.WINTER_ROUND)
    url = reverse(
        "reports:export_course",
        kwargs={"offering_id": target.pk, "window_id": closed.pk, "fmt": fmt},
    )

    assert client_for(demo.HOD).get(url).status_code in REFUSED


@pytest.mark.parametrize("name", ["reports:export_department", "reports:export_pending"])
def test_a_head_naming_another_department_still_gets_only_their_own(seeded, name):
    eee = Department.objects.get(code=demo.EEE)
    url = reverse(name, kwargs={"fmt": "csv"}) + f"?department={eee.pk}"

    response = client_for(demo.HOD).get(url)

    assert response.status_code == 200
    body = response.content.decode()
    assert not any(code in body for code in demo.WINTER_EEE_COURSES)
    assert not any(external_id in body for external_id in demo.EEE_STUDENT_IDS)


def test_a_head_cannot_list_pending_students_of_another_departments_course(seeded):
    target = offering(demo.WINTER, "EEE-2101")
    response = client_for(demo.HOD).get(reverse("reports:hod_pending"), {"course": target.pk})

    assert response.status_code in {200, *REFUSED}
    assert not any(external_id.encode() in response.content for external_id in demo.EEE_STUDENT_IDS)


@pytest.mark.parametrize("name", ["feedback:form", "feedback:done"])
def test_a_student_cannot_open_a_course_they_do_not_take(seeded, name):
    target = offering(demo.WINTER, "EEE-2101")
    url = reverse(
        name, kwargs={"window_id": window(demo.WINTER_ROUND).pk, "offering_id": target.pk}
    )

    assert client_for(demo.STUDENT).get(url).status_code in REFUSED


@pytest.mark.parametrize("name", ["feedback:draft", "feedback:precheck"])
def test_a_student_cannot_save_a_draft_for_a_course_they_do_not_take(seeded, name):
    target = offering(demo.WINTER, "EEE-2101")
    kwargs = {"window_id": window(demo.SUMMER_ROUND).pk, "offering_id": target.pk}
    if name == "feedback:precheck":
        kwargs["question_id"] = 1

    response = client_for(demo.STUDENT).post(reverse(name, kwargs=kwargs), {"q1": "x"})

    assert response.status_code in REFUSED


def test_nobody_opens_someone_elses_notification(seeded):
    from apps.accounts.models import User

    owner = User.objects.get(username=demo.TEACHER)
    notice = Notification.objects.create(user=owner, kind="round_opened", params={}, url="/")
    for intruder in (demo.STUDENT, demo.HOD, demo.ADMIN):
        url = reverse("notifications:open", args=[notice.pk])
        assert client_for(intruder).post(url).status_code == 404
    notice.refresh_from_db()
    assert notice.read_at is None
