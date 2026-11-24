"""``manage.py explain_visibility``: the operator's checklist agrees with the pages and leaks
nothing secret."""

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import IdRegistry
from apps.enrollment.models import EnrollmentStatus
from tests.e2e.test_full_journey import PASSWORD, give_feedback, sign_up

pytestmark = pytest.mark.django_db


def explain(external_id) -> str:
    out = StringIO()
    call_command("explain_visibility", registry_id=external_id, stdout=out)
    return out.getvalue()


def test_a_student_checklist_names_courses_rounds_and_receipts(term):
    office, now = term.office, timezone.now()
    alice = office.register_student("S-001", term.cse, term.bsc, term.first)
    office.enroll(alice, term.offerings["CSE201"], EnrollmentStatus.RETAKE)
    office.issue_codes(alice)
    code = office.codes["S-001"]
    alice_web = sign_up(office, alice)
    window = office.open_round(
        term.current, "Mid-term", now - timedelta(hours=1), now + timedelta(days=3)
    )
    give_feedback(alice_web, window, term.offerings["CSE101"])

    report = explain("s-001")  # the ID as an operator might type it
    username = IdRegistry.objects.get(pk=alice.registry_id).claimed_by.username
    assert f"[ok] Account: {username} · student" in report
    assert term.current.name in report
    assert "Courses on the dashboard: CSE101, CSE201" in report
    assert "Mid-term · open · covers: CSE101, CSE201 · submitted: 1/2" in report
    assert "Enrollments in other semesters" not in report
    for secret in (PASSWORD, code, "Helpful classes.", "Student S-001", "argon2"):
        assert secret not in report


def test_a_student_with_a_missing_level_term_course_is_flagged(term):
    office = term.office
    alice = office.register_student("S-001", term.cse, term.bsc, term.first)
    enrollment = alice.enrollments.get()
    office.post("enrollment:remove", {}, enrollment.pk)
    report = explain("S-001")
    assert "[!!] Account: Not signed up yet" in report
    assert "[!!] Courses on the dashboard: -" in report
    assert "[!!] Level/term courses not enrolled: CSE101" in report
    assert "No round in this semester yet." in report


def test_a_teacher_checklist_shows_only_the_current_semester(term):
    office = term.office
    report = explain("T-100")
    assert "Courses on the dashboard: CSE101, CSE102, CSE201" in report
    assert "Offerings in other semesters (not shown): 1" in report
    assert "Head of department: -" in report

    office.issue_codes(term.teacher)
    teacher_web = sign_up(office, term.teacher)
    page = teacher_web.get(reverse("accounts:dashboard_teacher"))
    shown = ", ".join(course.offering.course.code for course in page.context["courses"])
    assert f"Courses on the dashboard: {shown}" in report


def test_an_unknown_id_is_an_error():
    with pytest.raises(CommandError):
        explain("NOPE-1")
