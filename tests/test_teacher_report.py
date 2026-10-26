"""The teacher's pages (P14): overview, course report, comment lists, print view, action note.

Django test-client HTML tests. The 360px layout and the dark theme are checked by hand.
"""

import re
from dataclasses import dataclass
from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils import timezone, translation

from apps.academics.models import CourseOffering, CourseType
from apps.analytics import services as analytics
from apps.analytics.services import InsufficientData
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
from apps.reports.models import ActionNote
from apps.reports.services import teacher as report_service
from apps.reports.services.access import access_for
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
OPTIONS = [{"value": value, "en": value.upper(), "bn": value} for value in ("a", "b")]
NOT_RELEASED = "Results are released after the round closes."
NOT_ENOUGH = "Not enough responses to show this."
POSITIVE = "Very helpful and friendly, clear lectures"
NEGATIVE = "Not good, the lectures are confusing"
NEUTRAL = "Lectures were okay"


@pytest.fixture(autouse=True)
def _english():
    with translation.override("en"):
        yield


@dataclass
class World:
    department: object
    semester: object
    window: FeedbackWindow
    teacher: object
    user: object
    offering: CourseOffering
    categories: list
    ratings: list
    choice: Question
    yes_no: Question
    comment: Question

    def submit(self, count=1, *, offering=None, window=None, rating=4, texts=()):
        """``count`` students answer; ``texts`` are dealt out to them in turn."""
        offering = offering or self.offering
        window = window or self.window
        for index in range(count):
            student = make_student(self.department)
            Enrollment.objects.get_or_create(student_profile=student, offering=offering)
            SubmissionReceipt.objects.create(
                student_profile=student, offering=offering, window=window
            )
            response = FeedbackResponse.objects.create(offering=offering, window=window)
            answers = [
                Answer(response=response, question=question, int_value=rating)
                for question in self.ratings
            ]
            answers.append(Answer(response=response, question=self.yes_no, choice_value="yes"))
            answers.append(Answer(response=response, question=self.choice, choice_value="a"))
            if texts:
                answers.append(
                    Answer(
                        response=response,
                        question=self.comment,
                        encrypted_text=texts[index % len(texts)],
                    )
                )
            Answer.objects.bulk_create(answers)

    def url(self, name="course", *, offering=None, window=None, **extra):
        args = [(offering or self.offering).pk, (window or self.window).pk, *extra.values()]
        return reverse(f"reports:{name}", args=args)


@pytest.fixture
def world():
    department = DepartmentFactory()
    semester = make_semester(current=True)
    profile = make_teacher(department)
    user = claim(profile)
    offering = make_offering(
        make_course(department, course_type=CourseType.THEORY), semester, teacher=profile
    )
    categories = [
        QuestionCategory.objects.get_or_create(name=name)[0]
        for name in ("Teaching", "Content", "Assessment")
    ]
    # Created out of order on purpose: the report must follow ``order``, not the key.
    comment = make_question(QuestionType.TEXT, order=6, text="What would you change?")
    yes_no = make_question(QuestionType.YES_NO, order=5, text="Would you recommend it?")
    choice = make_question(QuestionType.CHOICE, order=4, options=OPTIONS, text="Pick one")
    ratings = [
        make_question(QuestionType.RATING, order=order, category=category, text=f"Rate {category}")
        for order, category in zip((3, 2, 1), reversed(categories), strict=True)
    ]
    return World(
        department=department,
        semester=semester,
        window=make_window(semester, **CLOSED),
        teacher=profile,
        user=user,
        offering=offering,
        categories=categories,
        ratings=ratings,
        choice=choice,
        yes_no=yes_no,
        comment=comment,
    )


@pytest.fixture
def teacher_client(web, world):
    sign_in(web, world.user)
    return web


def page(client, url, **params):
    response = client.get(url, params)
    assert response.status_code == 200
    return response.content.decode()


class TestAccess:
    def test_another_teacher_gets_403_on_every_course_page(self, web, world):
        world.submit(6)
        sign_in(web, claim(make_teacher(world.department)))
        for name in ("course", "print"):
            assert web.get(world.url(name)).status_code == 403
        assert web.get(world.url("comments", question_id=world.comment.pk)).status_code == 403
        assert web.post(world.url("note"), {"text": "x"}).status_code == 403
        assert not ActionNote.objects.exists()

    def test_hod_of_another_department_gets_403(self, web, world):
        sign_in(web, make_hod())
        assert web.get(world.url()).status_code == 403

    def test_students_and_visitors_are_refused(self, web, world):
        assert web.get(world.url()).status_code == 302
        student = claim(make_student(world.department))
        sign_in(web, student)
        assert web.get(world.url()).status_code == 403
        assert web.get(reverse("reports:overview")).status_code == 403

    def test_own_hod_and_admin_may_read(self, web, world):
        world.submit(6)
        sign_in(web, make_hod(world.department))
        assert web.get(world.url()).status_code == 200
        sign_in(web, make_admin())
        assert web.get(world.url()).status_code == 200

    def test_access_rules_in_the_service(self, world):
        assert access_for(world.user, world.offering).can_write_note
        assert not access_for(make_hod(world.department), world.offering).can_write_note
        with pytest.raises(PermissionDenied):
            access_for(claim(make_teacher(world.department)), world.offering)

    def test_unknown_offering_and_uncovered_round_are_404(self, teacher_client, world):
        assert (
            teacher_client.get(reverse("reports:course", args=[9999, world.window.pk])).status_code
            == 404
        )
        other_semester = make_semester(name="Fall 2026")
        elsewhere = make_window(other_semester, **CLOSED)
        assert teacher_client.get(world.url(window=elsewhere)).status_code == 404


class TestRelease:
    def test_open_round_shows_only_the_waiting_message(self, teacher_client, world):
        open_round = make_window(world.semester, **OPEN)
        world.submit(8, window=open_round, rating=5, texts=[POSITIVE])
        html = page(teacher_client, world.url(window=open_round))
        assert NOT_RELEASED in html
        assert POSITIVE not in html
        assert "Answers, question by question" not in html
        assert "not responded" not in html

    def test_too_few_responses_hide_everything(self, teacher_client, world):
        world.submit(4, texts=[POSITIVE])
        html = page(teacher_client, world.url())
        assert NOT_ENOUGH in html
        assert POSITIVE not in html
        assert "Rate Teaching" not in html

    def test_report_appears_with_enough_responses(self, teacher_client, world):
        world.submit(5, rating=4, texts=[POSITIVE])
        html = page(teacher_client, world.url())
        assert "Rate Teaching" in html
        assert POSITIVE in html
        assert "Round closed on" in html


class TestReportContent:
    def test_questions_follow_the_question_order(self, teacher_client, world):
        world.submit(6, texts=[POSITIVE])
        html = page(teacher_client, world.url())
        expected = [
            "Rate Teaching",
            "Rate Content",
            "Rate Assessment",
            "Pick one",
            "Would you recommend it?",
            "What would you change?",
        ]
        titles = re.findall(r'<h3 id="qt\d+"[^>]*>.*?</span>\s*(.*?)</h3>', html, flags=re.S)
        assert [title.strip() for title in titles] == expected
        report = report_service.build_report(world.offering, world.window, world.user)
        assert [block.question.text for block in report.blocks] == expected
        assert [block.number for block in report.blocks] == [1, 2, 3, 4, 5, 6]

    def test_rating_shows_average_stars_and_distribution(self, teacher_client, world):
        world.submit(3, rating=5)
        world.submit(3, rating=3)
        html = page(teacher_client, world.url())
        assert "4.0" in html
        assert "4.0 out of 5" in html
        assert html.count('class="bar-val"') >= 5 * 3
        assert 'width="50.0"' in html
        assert "5 star" in html

    def test_choice_questions_show_percent_bars_with_option_labels(self, teacher_client, world):
        world.submit(6)
        html = page(teacher_client, world.url())
        assert "100%" in html
        assert ">A<" in html or "A\n" in html or "A</span>" in html
        assert "Yes" in html

    def test_overall_average_and_pending_count(self, teacher_client, world):
        world.submit(6, rating=5)
        extra = make_student(world.department)
        Enrollment.objects.create(student_profile=extra, offering=world.offering)
        summary = report_service.summarize(world.offering, world.window, world.user, timezone.now())
        assert summary.average == 5.0
        assert summary.pending == 1
        html = page(teacher_client, world.url())
        assert "1 student has not responded" in html

    def test_radar_trend_and_department_comparison(self, teacher_client, world):
        world.submit(6, rating=4)
        peer = make_teacher(world.department)
        peer_offering = make_offering(
            make_course(world.department, code="CSE202"), world.semester, teacher=peer
        )
        world.submit(6, offering=peer_offering, rating=2)
        earlier = make_window(
            world.semester, opens=timedelta(days=-9), closes=timedelta(days=-7), name="Early"
        )
        world.submit(5, window=earlier, rating=3)
        html = page(teacher_client, world.url())
        assert 'id="radar-data"' in html
        assert "Department average" in html
        assert 'id="trend-data"' in html
        assert "above the department average" in html or "below the department average" in html

    def test_department_scores_need_two_teachers_and_enough_answers(self, world):
        world.submit(6, rating=4)
        alone = analytics.department_category_scores(world.window, world.department)
        assert isinstance(alone, InsufficientData)
        peer_offering = make_offering(
            make_course(world.department, code="CSE203"),
            world.semester,
            teacher=make_teacher(world.department),
        )
        world.submit(5, offering=peer_offering, rating=2)
        analytics.invalidate(world.window)
        scores = analytics.department_category_scores(world.window, world.department)
        assert set(scores) == {category.pk for category in world.categories}
        assert set(scores.values()) == {round((4 * 6 + 2 * 5) / 11, 2)}

    def test_department_scores_wait_for_the_round_to_close(self, world):
        open_round = make_window(world.semester, **OPEN)
        result = analytics.department_category_scores(open_round, world.department)
        assert result.reason == analytics.Reason.NOT_RELEASED

    def test_insights_without_department_use_a_fixed_bar(self, world):
        world.submit(6, rating=5)
        report = report_service.build_report(world.offering, world.window, world.user)
        assert len(report.strengths) == report_service.INSIGHT_LIMIT
        assert report.improve == ()

    def test_word_cloud_lists_words_used_more_than_once(self, teacher_client, world):
        world.submit(6, texts=[POSITIVE])
        html = page(teacher_client, world.url())
        assert "Words that come up most" in html
        assert 'class="cloud-' in html

    def test_no_identity_or_timestamps_in_the_page(self, teacher_client, world):
        world.submit(6, texts=[POSITIVE, NEGATIVE])
        for url in (world.url(), world.url("print")):
            html = page(teacher_client, url)
            for response in FeedbackResponse.objects.all():
                assert str(response.pk) not in html
            for answer in Answer.objects.all()[:5]:
                assert str(answer.pk) not in html
            assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-", html)
            assert "<time" not in html
            assert "datetime=" not in html
            assert not re.search(r"\d{1,2}:\d{2}", html)
            assert "Rahim Uddin" not in html
            assert "style=" not in html
            assert "onclick" not in html


class TestComments:
    def test_comments_are_tagged_and_shuffled_stably(self, teacher_client, world):
        world.submit(9, texts=[POSITIVE, NEGATIVE, NEUTRAL])
        first = page(teacher_client, world.url())
        again = page(teacher_client, world.url())

        def order(html):
            return re.findall(r"<p>(Very helpful[^<]*|Not good[^<]*|Lectures were[^<]*)</p>", html)

        assert order(first) == order(again)
        assert len(order(first)) == 9
        assert "Positive" in first and "Needs work" in first and "Neutral" in first

    def test_pagination_through_the_fragment_endpoint(self, teacher_client, world):
        world.submit(13, texts=[POSITIVE])
        url = world.url("comments", question_id=world.comment.pk)
        first = teacher_client.get(url, headers={"HX-Request": "true"})
        assert first.content.decode().count('class="comment"') == 10
        assert "Showing 1-10 of 13" in first.content.decode()
        second = teacher_client.get(url, {"page": 2}, headers={"HX-Request": "true"})
        assert second.content.decode().count('class="comment"') == 3
        assert "<html" not in second.content.decode()

    def test_plain_request_to_the_fragment_url_shows_the_full_page(self, teacher_client, world):
        world.submit(6, texts=[POSITIVE])
        url = world.url("comments", question_id=world.comment.pk)
        response = teacher_client.get(url, {"q": "friendly"})
        assert response.status_code == 302
        assert f"question={world.comment.pk}" in response["Location"]
        assert "q=friendly" in response["Location"]

    def test_search_and_tag_narrow_the_list(self, teacher_client, world):
        world.submit(12, texts=[POSITIVE, POSITIVE, NEGATIVE])
        url = world.url()
        html = page(teacher_client, url, question=world.comment.pk, q="friendly")
        assert html.count('class="comment"') == 8
        html = page(teacher_client, url, question=world.comment.pk, tag="positive")
        assert html.count('class="comment"') == 8
        assert NEGATIVE not in html

    def test_a_narrowed_slice_below_the_threshold_stays_hidden(self, teacher_client, world):
        world.submit(
            8,
            texts=[POSITIVE, POSITIVE, POSITIVE, POSITIVE, POSITIVE, POSITIVE, POSITIVE, NEGATIVE],
        )
        html = page(teacher_client, world.url(), question=world.comment.pk, tag="negative")
        assert NEGATIVE not in html
        assert NOT_ENOUGH in html

    def test_no_match_says_so(self, teacher_client, world):
        world.submit(6, texts=[POSITIVE])
        html = page(teacher_client, world.url(), question=world.comment.pk, q="zebra")
        assert "No comments match." in html

    def test_bad_query_values_are_ignored(self, teacher_client, world):
        world.submit(6, texts=[POSITIVE])
        html = page(teacher_client, world.url(), question=world.comment.pk, page="x", tag="evil")
        assert html.count('class="comment"') == 6
        assert teacher_client.get(world.url(), {"question": "abc"}).status_code == 200

    def test_comment_html_is_escaped(self, teacher_client, world):
        world.submit(6, texts=["<script>alert(1)</script> ok"])
        html = page(teacher_client, world.url())
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_print_view_lists_every_comment_without_controls(self, teacher_client, world):
        world.submit(13, texts=[POSITIVE])
        html = page(teacher_client, world.url("print"))
        assert html.count('class="comment"') == 13
        assert "Search comments" not in html
        assert "data-print" in html


class TestNote:
    def test_teacher_saves_and_hod_reads_it(self, web, world):
        world.submit(6)
        sign_in(web, world.user)
        response = web.post(world.url("note"), {"text": "Added office hours."})
        assert response.status_code == 302
        assert ActionNote.objects.get().text == "Added office hours."
        assert "Added office hours." in page(web, world.url())
        sign_in(web, make_hod(world.department))
        html = page(web, world.url())
        assert "Added office hours." in html
        assert "Save note" not in html
        assert web.post(world.url("note"), {"text": "mine now"}).status_code == 403
        assert ActionNote.objects.get().text == "Added office hours."

    def test_saving_again_replaces_and_an_empty_note_removes_it(self, teacher_client, world):
        world.submit(6)
        teacher_client.post(world.url("note"), {"text": "First"})
        teacher_client.post(world.url("note"), {"text": "Second"})
        assert ActionNote.objects.get().text == "Second"
        teacher_client.post(world.url("note"), {"text": "   "})
        assert not ActionNote.objects.exists()

    def test_note_is_refused_before_the_round_closes_and_when_too_long(self, teacher_client, world):
        open_round = make_window(world.semester, **OPEN)
        assert (
            teacher_client.post(world.url("note", window=open_round), {"text": "x"}).status_code
            == 404
        )
        teacher_client.post(world.url("note"), {"text": "x" * 2001})
        assert not ActionNote.objects.exists()

    def test_note_form_needs_a_post(self, teacher_client, world):
        assert teacher_client.get(world.url("note")).status_code == 405


class TestOverview:
    def test_lists_only_my_courses_with_rate_and_average(self, teacher_client, world):
        world.submit(6, rating=4)
        other = make_offering(
            make_course(world.department, code="CSE999", title="Hidden"),
            world.semester,
            teacher=make_teacher(world.department),
        )
        html = page(teacher_client, reverse("reports:overview"))
        assert world.offering.course.code in html
        assert "CSE999" not in html
        assert "6 of 6 responded (100%)" in html
        assert "4.0" in html
        assert other.course.code not in html

    def test_an_open_round_shows_no_figures(self, teacher_client, world):
        open_round = make_window(world.semester, **OPEN)
        world.submit(6, window=open_round)
        html = page(teacher_client, reverse("reports:overview"), round=open_round.pk)
        assert NOT_RELEASED in html
        assert "responded" not in html

    def test_round_selector_defaults_to_the_newest_closed_round(self, teacher_client, world):
        make_window(world.semester, **OPEN)
        html = page(teacher_client, reverse("reports:overview"))
        assert f'value="{world.window.pk}" selected' in html

    def test_without_rounds_there_is_an_empty_state(self, web):
        sign_in(web, claim(make_teacher()))
        assert "No feedback round yet" in page(web, reverse("reports:overview"))

    def test_teacher_navigation_links_to_the_overview(self, teacher_client):
        assert reverse("reports:overview") in page(
            teacher_client, reverse("accounts:dashboard_teacher")
        )

    def test_only_teachers_open_the_overview(self, web):
        sign_in(web, make_admin())
        assert web.get(reverse("reports:overview")).status_code == 403
