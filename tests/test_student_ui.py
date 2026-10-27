"""The student's pages (P12): dashboard, feedback form, drafts, pre-check, profile.

Django test-client HTML tests. The 360px layout is checked by hand (see the P12 report).
"""

import io
import re
from dataclasses import dataclass
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.academics.models import CourseType
from apps.accounts.models import User
from apps.auditlog.models import AuditEvent
from apps.core.models import ActiveSession
from apps.enrollment.models import Enrollment
from apps.feedback.models import (
    Answer,
    AppliesTo,
    Draft,
    FeedbackResponse,
    FeedbackWindow,
    Question,
    QuestionCategory,
    QuestionType,
    SubmissionReceipt,
)
from apps.feedback.services import portal
from tests.factories import PASSWORD, DepartmentFactory, claim, make_admin, make_student, sign_in
from tests.test_academics import make_course, make_offering, make_semester
from tests.test_feedback_core import enrolled_student, make_question, make_window

pytestmark = pytest.mark.django_db


@dataclass
class World:
    web: object
    user: User
    profile: object
    offering: object
    window: FeedbackWindow
    questions: dict[str, Question]

    @property
    def form_url(self):
        return reverse("feedback:form", args=[self.window.pk, self.offering.pk])

    @property
    def draft_url(self):
        return reverse("feedback:draft", args=[self.window.pk, self.offering.pk])

    @property
    def done_url(self):
        return reverse("feedback:done", args=[self.window.pk, self.offering.pk])

    def check_url(self, question):
        return reverse("feedback:precheck", args=[self.window.pk, self.offering.pk, question.pk])

    def post(self, *, password=PASSWORD, **overrides):
        """Submit the whole form; ``overrides`` replace or (with ``None``) drop an answer."""
        q = self.questions
        data = {
            "qset": portal.fingerprint(portal.form_questions(self.offering)),
            f"q{q['rating'].pk}": "4",
            f"q{q['likert'].pk}": "5",
            f"q{q['choice'].pk}": "b",
            f"q{q['yes_no'].pk}": "yes",
            f"q{q['comment'].pk}": "Clear lectures, more examples please.",
            "password": password,
        }
        for name, value in overrides.items():
            key = f"q{q[name].pk}" if name in q else name
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        return self.web.post(self.form_url, data)


@pytest.fixture
def world(web):
    department = DepartmentFactory(name="Computer Science", name_bn="কম্পিউটার সায়েন্স")
    semester = make_semester(current=True)
    course = make_course(
        department, code="CSE2205", title="Operating Systems", title_bn="অপারেটিং সিস্টেম"
    )
    offering = make_offering(course, semester)
    window = make_window(semester, name="Midterm round")
    profile = enrolled_student(offering, PASSWORD)
    teaching = QuestionCategory.objects.create(name="Test delivery", name_bn="পাঠদান", order=1)
    content = QuestionCategory.objects.create(name="Test material", name_bn="বিষয়বস্তু", order=2)
    options = [{"value": v, "en": v.upper(), "bn": v} for v in ("a", "b", "c")]
    questions = {
        "rating": make_question(
            QuestionType.RATING,
            order=1,
            category=teaching,
            text="The teacher explains clearly.",
            text_bn="শিক্ষক স্পষ্টভাবে বোঝান।",
        ),
        "likert": make_question(
            QuestionType.LIKERT, order=2, category=teaching, text="The teacher is prepared."
        ),
        "choice": make_question(
            QuestionType.CHOICE,
            order=3,
            category=content,
            options=options,
            text="The pace of the course is",
        ),
        "yes_no": make_question(
            QuestionType.YES_NO, order=4, category=content, required=False, text="Is it relevant?"
        ),
        "comment": make_question(
            QuestionType.TEXT, order=5, category=content, text="What should improve?"
        ),
        "remark": make_question(
            QuestionType.TEXT, order=6, category=content, required=False, text="Anything else?"
        ),
        "lab_only": make_question(
            QuestionType.RATING, order=7, applies_to=AppliesTo.LAB, text="Lab equipment is enough."
        ),
    }
    user = profile.registry.claimed_by
    sign_in(web, user)
    return World(web, user, profile, offering, window, questions)


def dashboard(web):
    return web.get(reverse("accounts:dashboard_student"))


def other_offering(world, **course_fields):
    """A course of the current semester that the student is not enrolled in."""
    course = make_course(
        world.offering.course.department, code=course_fields.pop("code", "CSE9999"), **course_fields
    )
    return make_offering(course, world.offering.semester)


def student_pages(world):
    """Every page a student can load, as URLs."""
    return [
        reverse("accounts:dashboard_student"),
        world.form_url,
        reverse("accounts:account"),
        reverse("accounts:profile"),
        reverse("accounts:password_change"),
    ]


# --- dashboard ---------------------------------------------------------------------------


def test_dashboard_shows_profile_round_and_enrolled_course(world):
    world.user.nickname = "Tanvir"
    world.user.save()
    html = dashboard(world.web).content.decode()
    assert "Tanvir" in html
    assert world.user.username in html
    assert "Computer Science" in html
    assert "Midterm round" in html
    assert "CSE2205" in html and "Operating Systems" in html
    assert "Karim Sir" in html
    assert "Pending" in html and "Give feedback" in html
    assert 'aria-label="0 of 1 done"' in html
    assert "Closes in" in html and 'role="timer"' in html
    assert "Your feedback is anonymous" in html
    assert world.form_url in html


def test_dashboard_is_in_bangla_when_asked(world):
    world.web.defaults["HTTP_ACCEPT_LANGUAGE"] = "bn"
    html = dashboard(world.web).content.decode()
    assert "কম্পিউটার সায়েন্স" in html
    assert "অপারেটিং সিস্টেম" in html


def test_only_enrolled_courses_are_listed(world):
    stranger = other_offering(world, title="Secret Seminar")
    other_semester = make_offering(
        make_course(world.offering.course.department, code="CSE0001", title="Old Course"),
        make_semester(start_date="2025-07-01", end_date="2025-12-31"),
    )
    other_student = enrolled_student(stranger)
    html = dashboard(world.web).content.decode()
    assert "Operating Systems" in html
    assert "Secret Seminar" not in html and "Old Course" not in html
    assert reverse("feedback:form", args=[world.window.pk, stranger.pk]) not in html
    assert other_semester.course.title not in html
    assert other_student.registry.external_id not in html


def test_not_enrolled_student_sees_the_empty_state(web):
    make_semester(current=True)
    user = make_student_user()
    sign_in(web, user)
    html = dashboard(web).content.decode()
    assert "You are not enrolled in any course this semester" in html
    assert "Give feedback" not in html


def test_no_current_semester_shows_an_empty_state(web):
    sign_in(web, make_student_user())
    assert "No current semester" in dashboard(web).content.decode()


def make_student_user():
    return claim(make_student())


def test_no_round_yet_is_explained(world):
    FeedbackWindow.objects.all().delete()
    html = dashboard(world.web).content.decode()
    assert "No feedback round has been announced" in html
    assert "No round yet" in html
    assert "Give feedback" not in html


def test_upcoming_round_shows_opening_and_no_button(world):
    FeedbackWindow.objects.update(
        opens_at=timezone.now() + timedelta(days=2), closes_at=timezone.now() + timedelta(days=9)
    )
    html = dashboard(world.web).content.decode()
    assert "Opens in" in html
    assert "Give feedback" not in html


def test_closed_round_marks_unsubmitted_courses(world):
    FeedbackWindow.objects.update(
        opens_at=timezone.now() - timedelta(days=9), closes_at=timezone.now() - timedelta(days=1)
    )
    html = dashboard(world.web).content.decode()
    assert "Window closed" in html
    assert "Give feedback" not in html


def test_submitted_course_is_sealed_and_counted(world):
    assert world.post().status_code == 302
    html = dashboard(world.web).content.decode()
    assert "Submitted" in html and "Sealed" in html
    assert 'aria-label="1 of 1 done"' in html
    assert "Give feedback" not in html


def test_dashboard_never_shows_the_student_id_or_name(world, settings):
    registry = world.profile.registry
    for url in student_pages(world):
        html = world.web.get(url).content.decode()
        assert registry.external_id not in html, url
        assert registry.full_name not in html, url
    assert world.post().status_code == 302
    for url in [*student_pages(world), world.done_url, world.form_url]:
        html = world.web.get(url).content.decode()
        assert registry.external_id not in html, url
        assert registry.full_name not in html, url


def test_own_id_is_shown_only_when_the_setting_is_on(world, settings):
    external_id = world.profile.registry.external_id
    settings.SHOW_OWN_ID_TO_STUDENT = True
    html = dashboard(world.web).content.decode()
    assert external_id in html
    assert world.profile.registry.full_name not in html


def test_teacher_photo_is_shown_on_the_course_card(world, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    teacher = world.offering.teacher
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, format="PNG")
    teacher.photo.save("t.png", SimpleUploadedFile("t.png", buffer.getvalue()), save=True)
    assert f'src="{teacher.photo.url}"' in dashboard(world.web).content.decode()


def test_student_pages_have_no_inline_script_or_style(world):
    for url in student_pages(world):
        html = world.web.get(url).content.decode()
        assert not re.search(r"<script(?![^>]*\bsrc=)", html), url
        assert not re.search(r"\sstyle=|\sonclick=|\sonchange=", html), url


def test_only_students_may_use_the_student_pages(world, client):
    teacher_user = claim(world.offering.teacher)
    for user in (teacher_user, make_admin()):
        client.logout()
        sign_in(client, user)
        assert client.get(world.form_url).status_code == 403
        assert client.get(reverse("accounts:dashboard_student")).status_code == 403
        assert client.post(world.draft_url, {}).status_code == 403


# --- access to other courses -------------------------------------------------------------


def test_other_courses_and_rounds_are_not_found_without_leaking_existence(world):
    stranger = other_offering(world, title="Secret Seminar")
    missing = 987654
    urls = [
        ("feedback:form", [world.window.pk, stranger.pk]),
        ("feedback:form", [world.window.pk, missing]),
        ("feedback:form", [missing, world.offering.pk]),
        ("feedback:draft", [world.window.pk, stranger.pk]),
        ("feedback:done", [world.window.pk, stranger.pk]),
        ("feedback:precheck", [world.window.pk, stranger.pk, world.questions["comment"].pk]),
    ]
    for name, args in urls:
        method = world.web.get if name in ("feedback:form", "feedback:done") else world.web.post
        response = method(reverse(name, args=args))
        assert response.status_code == 404, (name, args)
        assert "Secret Seminar" not in response.content.decode()
    assert Draft.objects.count() == 0
    assert (
        world.web.post(
            reverse("feedback:form", args=[world.window.pk, stranger.pk]), {"password": PASSWORD}
        ).status_code
        == 404
    )
    assert SubmissionReceipt.objects.count() == 0


def test_round_outside_the_courses_scope_is_not_found(world):
    other_department = DepartmentFactory()
    scoped = make_window(world.offering.semester, name="Scoped round")
    FeedbackWindow.objects.filter(pk=world.window.pk).update(is_active=False)
    scoped.departments.add(other_department)
    url = reverse("feedback:form", args=[scoped.pk, world.offering.pk])
    assert world.web.get(url).status_code == 404
    assert world.web.get(world.form_url).status_code == 404


# --- the form ----------------------------------------------------------------------------


def test_form_shows_the_questions_for_this_course_grouped_by_category(world):
    html = world.web.get(world.form_url).content.decode()
    assert "Feedback for Karim Sir" in html
    assert "Do not write your name or personal details" in html
    assert html.index("Test delivery") < html.index("Test material")
    assert html.index("The teacher explains clearly.") < html.index("The pace of the course is")
    assert "Lab equipment is enough." not in html
    assert html.count(f'name="q{world.questions["rating"].pk}"') == 5
    assert "5 out of 5" in html and "Not rated" in html
    assert "Strongly agree" in html
    assert "0</span> of 4 required answered" in html
    assert 'data-progress max="4"' in html
    assert "optional" in html
    assert 'name="password"' in html and "Final and anonymous" in html
    assert 'name="csrfmiddlewaretoken"' in html
    assert "js/feedback_form.js" in html


def test_form_is_in_bangla_when_asked(world):
    world.web.defaults["HTTP_ACCEPT_LANGUAGE"] = "bn"
    html = world.web.get(world.form_url).content.decode()
    assert "শিক্ষক স্পষ্টভাবে বোঝান।" in html
    assert "পাঠদান" in html


def test_lab_course_gets_the_lab_questions(world):
    lab = make_offering(
        make_course(world.offering.course.department, code="CSE2206", course_type=CourseType.LAB),
        world.offering.semester,
    )
    Enrollment.objects.create(student_profile=world.profile, offering=lab)
    html = world.web.get(reverse("feedback:form", args=[world.window.pk, lab.pk])).content.decode()
    assert "Lab equipment is enough." in html


def test_submitting_stores_the_answers_anonymously_and_shows_thanks(world):
    response = world.post()
    assert response.status_code == 302 and response["Location"] == world.done_url
    assert SubmissionReceipt.objects.filter(student_profile=world.profile).count() == 1
    stored = Answer.objects.get(question=world.questions["comment"])
    assert stored.encrypted_text == "Clear lectures, more examples please."
    assert FeedbackResponse.objects.count() == 1
    thanks = world.web.get(world.done_url).content.decode()
    assert "Thank you!" in thanks and "final and anonymous" in thanks
    assert "Back to my courses" in thanks
    assert AuditEvent.objects.filter(action="feedback.submitted").exists()


def test_thank_you_page_needs_a_submission(world):
    response = world.web.get(world.done_url)
    assert response.status_code == 302 and response["Location"] == world.form_url


def test_second_submit_is_blocked(world):
    assert world.post().status_code == 302
    again = world.post(comment="A different opinion entirely.")
    assert again.status_code == 409
    assert "You have already given feedback" in again.content.decode()
    assert FeedbackResponse.objects.count() == 1
    assert SubmissionReceipt.objects.count() == 1
    page = world.web.get(world.form_url)
    assert page.status_code == 200
    assert "You have already given feedback" in page.content.decode()
    assert 'name="password"' not in page.content.decode()


def test_missing_required_answers_are_refused_on_the_server(world):
    response = world.post(rating=None, comment="   ")
    html = response.content.decode()
    assert response.status_code == 400
    assert html.count("This question needs an answer.") == 2
    assert 'class="fq is-invalid"' in html
    assert SubmissionReceipt.objects.count() == 0
    assert "data-autoopen" not in html
    assert 'value="b" checked' in html  # the answers already given are kept


def test_wrong_password_keeps_the_answers_and_reopens_the_dialog(world):
    response = world.post(password="not-the-password-1")
    html = response.content.decode()
    assert response.status_code == 400
    assert "The password is not correct" in html
    assert "data-autoopen" in html
    assert "Clear lectures, more examples please." in html
    assert SubmissionReceipt.objects.count() == 0


def test_too_many_wrong_passwords_are_throttled(world):
    statuses = [world.post(password="nope-nope-nope-1").status_code for _ in range(12)]
    assert 429 in statuses
    assert SubmissionReceipt.objects.count() == 0
    assert world.post().status_code == 429


def test_changed_questions_are_noticed(world):
    stale = world.post()
    assert stale.status_code == 302
    other = enrolled_student(world.offering, PASSWORD)
    sign_in(world.web, other.registry.claimed_by)
    data = {"qset": "1,2,3", "password": PASSWORD}
    response = world.web.post(world.form_url, data)
    assert response.status_code == 409
    assert "The questions changed" in response.content.decode()
    assert SubmissionReceipt.objects.filter(student_profile=other).count() == 0


def test_closed_and_upcoming_rounds_block_the_form(world):
    FeedbackWindow.objects.update(closes_at=timezone.now() - timedelta(minutes=1))
    page = world.web.get(world.form_url)
    assert page.status_code == 200 and "This round is closed" in page.content.decode()
    posted = world.post()
    assert posted.status_code == 409 and SubmissionReceipt.objects.count() == 0
    FeedbackWindow.objects.update(
        opens_at=timezone.now() + timedelta(days=1), closes_at=timezone.now() + timedelta(days=5)
    )
    assert "has not opened yet" in world.web.get(world.form_url).content.decode()


# --- draft autosave and the comment pre-check ----------------------------------------------


def test_draft_is_saved_and_comes_back_on_the_form(world):
    q = world.questions
    response = world.web.post(
        world.draft_url,
        {f"q{q['rating'].pk}": "3", f"q{q['comment'].pk}": "Half written", "password": "x"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200 and "Draft saved" in response.content.decode()
    assert Draft.objects.count() == 1
    html = world.web.get(world.form_url).content.decode()
    assert "Half written" in html
    assert re.search(r'value="3"\s+checked', html)


def test_the_password_is_never_part_of_a_draft(world):
    q = world.questions
    world.web.post(world.draft_url, {f"q{q['comment'].pk}": "text", "password": "Secret-pw-123"})
    assert "Secret-pw-123" not in Draft.objects.get().payload


def test_draft_is_deleted_by_the_submission(world):
    world.web.post(world.draft_url, {f"q{world.questions['comment'].pk}": "Half written"})
    assert world.post().status_code == 302
    assert Draft.objects.count() == 0


def test_no_draft_after_submission_or_after_the_round_closed(world):
    assert world.post().status_code == 302
    response = world.web.post(world.draft_url, {f"q{world.questions['comment'].pk}": "late"})
    assert "already given feedback" in response.content.decode()
    assert Draft.objects.count() == 0


def test_a_lost_session_redirects_htmx_requests_to_the_login_page(client, world):
    client.logout()
    response = client.post(world.draft_url, {}, HTTP_HX_REQUEST="true")
    assert response.status_code == 401
    assert response["HX-Redirect"].startswith(reverse("accounts:login"))
    assert client.post(world.draft_url, {}).status_code == 302


def test_precheck_tells_what_the_filter_would_remove(world):
    comment = world.questions["comment"]
    dirty = world.web.post(
        world.check_url(comment), {f"q{comment.pk}": "Call me on 01712345678 about it."}
    )
    html = dirty.content.decode()
    assert "Phone numbers" in html and "This is what will be saved:" in html
    assert "01712345678" not in html
    clean = world.web.post(world.check_url(comment), {f"q{comment.pk}": "Very helpful teacher."})
    assert "Looks fine." in clean.content.decode()
    empty = world.web.post(world.check_url(comment), {f"q{comment.pk}": ""})
    assert empty.content.decode().strip() == ""
    assert Draft.objects.count() == 0 and Answer.objects.count() == 0


def test_precheck_only_serves_text_questions_of_this_form(world):
    rating = world.questions["rating"]
    lab_only = world.questions["lab_only"]
    assert world.web.post(world.check_url(rating), {}).status_code == 404
    assert world.web.post(world.check_url(lab_only), {}).status_code == 404


# --- profile -----------------------------------------------------------------------------


def png_upload(name="me.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), "blue").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def test_profile_offers_only_the_editable_fields(world):
    response = world.web.get(reverse("accounts:profile"))
    assert list(response.context["form"].fields) == [
        "nickname",
        "avatar",
        "remove_avatar",
        "language",
        "theme",
    ]
    html = response.content.decode()
    assert world.user.username in html
    assert 'enctype="multipart/form-data"' in html


def test_profile_saves_choices_and_remembers_them(world):
    url = reverse("accounts:profile")
    response = world.web.post(
        url,
        {
            "nickname": "  Tanvir   R  ",
            "language": "en",
            "theme": "dark",
            "department": "999",
            "username": "hacker",
            "role": "admin",
        },
    )
    assert response.status_code == 302
    world.user.refresh_from_db()
    assert (world.user.nickname, world.user.language, world.user.theme) == (
        "Tanvir R",
        "en",
        "dark",
    )
    assert world.user.role == "student" and world.user.username != "hacker"
    assert world.user.department_id == world.profile.registry.department_id
    assert response.cookies["django_language"].value == "en"
    assert response.cookies["tfs_theme"].value == "dark"
    assert AuditEvent.objects.filter(action="account.profile_updated").exists()
    assert 'data-theme-pref="dark"' in world.web.get(url).content.decode()
    system = world.web.post(url, {"nickname": "", "language": "bn", "theme": "system"})
    assert system.cookies["tfs_theme"].value == ""


def test_profile_rejects_unknown_language_and_theme(world):
    response = world.web.post(
        reverse("accounts:profile"), {"nickname": "x", "language": "xx", "theme": "neon"}
    )
    assert response.status_code == 200
    assert set(response.context["form"].errors) == {"language", "theme"}


def test_avatar_is_reencoded_replaced_and_removed(
    world, settings, tmp_path, django_capture_on_commit_callbacks
):
    settings.MEDIA_ROOT = tmp_path
    url = reverse("accounts:profile")
    base = {"nickname": "T", "language": "en", "theme": "system"}
    assert world.web.post(url, {**base, "avatar": png_upload()}).status_code == 302
    world.user.refresh_from_db()
    first = world.user.avatar.name
    assert first.startswith("avatars/") and first.endswith(".webp")
    assert f'src="{world.user.avatar.url}"' in dashboard(world.web).content.decode()
    with django_capture_on_commit_callbacks(execute=True):
        assert world.web.post(url, {**base, "avatar": png_upload("again.png")}).status_code == 302
    world.user.refresh_from_db()
    second = world.user.avatar.name
    assert second != first and not (tmp_path / first).exists()
    with django_capture_on_commit_callbacks(execute=True):
        assert world.web.post(url, {**base, "remove_avatar": "on"}).status_code == 302
    world.user.refresh_from_db()
    assert not world.user.avatar and not (tmp_path / second).exists()


def test_avatar_that_is_not_an_image_is_refused(world, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    fake = SimpleUploadedFile("x.png", b"<?php echo 1; ?>", content_type="image/png")
    response = world.web.post(
        reverse("accounts:profile"),
        {"nickname": "", "language": "en", "theme": "system", "avatar": fake},
    )
    assert response.status_code == 200 and "avatar" in response.context["form"].errors
    world.user.refresh_from_db()
    assert not world.user.avatar


def test_account_page_links_to_profile_security_and_sessions(world):
    html = world.web.get(reverse("accounts:account")).content.decode()
    assert reverse("accounts:profile") in html
    assert reverse("accounts:password_change") in html
    assert reverse("accounts:two_factor") in html
    assert "Where you are signed in" in html


# --- proxy-prevention notices ---------------------------------------------------------------


def test_signing_in_on_a_new_device_is_announced_once(web):
    user = make_student_user()
    ActiveSession.objects.create(user=user, login_id="old", user_agent="Old phone", ip="10.0.0.5")
    sign_in(web, user)
    first = dashboard(web).content.decode()
    assert "signed in on another device" in first
    assert reverse("accounts:password_change") in first
    assert "signed in on another device" not in dashboard(web).content.decode()


def test_signing_in_again_on_the_same_device_is_not_announced(web):
    user = make_student_user()
    ActiveSession.objects.create(user=user, login_id="old", user_agent="", ip=None)
    sign_in(web, user)
    assert "signed in on another device" not in dashboard(web).content.decode()


def test_the_replaced_device_is_told_what_happened(web):
    user = make_student_user()
    sign_in(web, user)
    other = Client(HTTP_ACCEPT_LANGUAGE="en")
    sign_in(other, user)
    response = web.get(reverse("accounts:dashboard_student"), follow=True)
    assert response.redirect_chain[0][0].startswith(reverse("accounts:login"))
    html = response.content.decode()
    assert "signed in on another device" in html and "change your password" in html
