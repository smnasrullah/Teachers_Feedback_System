from dataclasses import dataclass
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import translation

from apps.academics.models import CourseOffering, CourseType
from apps.analytics import lexicon
from apps.analytics import services as analytics
from apps.analytics.services import InsufficientData, Reason, Sentiment
from apps.core.permissions import Role
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
from apps.feedback.services import anonymity
from tests.factories import DepartmentFactory, make_admin, make_student, make_teacher, make_user
from tests.test_academics import make_course, make_offering, make_semester
from tests.test_feedback_core import enrolled_student, make_question, make_window

pytestmark = pytest.mark.django_db

CLOSED = {"opens": timedelta(days=-3), "closes": timedelta(days=-1)}
OPTIONS = [{"value": value, "en": value.upper(), "bn": value} for value in ("a", "b", "c")]
COMMENTS = [
    "Clear lectures and helpful examples",
    "Very helpful and friendly, clear lectures",
    "Boring slides, the pace is slow",
    "Not good, the lectures are confusing",
    "ক্লাস খুব ভালো ছিল",
    "Lectures were okay",
]


@pytest.fixture(autouse=True)
def _english():
    with translation.override("en"):
        yield


@dataclass
class Setup:
    department: object
    semester: object
    window: FeedbackWindow
    offering: CourseOffering
    category: QuestionCategory
    rating: Question
    agree: Question
    yes_no: Question
    choice: Question
    comment: Question

    def respond(self, *, offering=None, window=None, rating=4, agree=5, choice="a", text=None):
        response = FeedbackResponse.objects.create(
            offering=offering or self.offering, window=window or self.window
        )
        rows = [
            Answer(response=response, question=self.rating, int_value=rating),
            Answer(response=response, question=self.agree, int_value=agree),
            Answer(response=response, question=self.yes_no, choice_value="yes"),
            Answer(response=response, question=self.choice, choice_value=choice),
        ]
        if text is not None:
            rows.append(Answer(response=response, question=self.comment, encrypted_text=text))
        Answer.objects.bulk_create(rows)
        return response

    def respond_many(self, count, **fields):
        for _ in range(count):
            self.respond(**fields)


@pytest.fixture
def setup():
    department = DepartmentFactory()
    semester = make_semester(current=True)
    category, _created = QuestionCategory.objects.get_or_create(name="Teaching")
    return Setup(
        department=department,
        semester=semester,
        window=make_window(semester, **CLOSED),
        offering=make_offering(make_course(department, course_type=CourseType.THEORY), semester),
        category=category,
        rating=make_question(QuestionType.RATING, order=1, category=category),
        agree=make_question(QuestionType.LIKERT, order=2, category=category),
        yes_no=make_question(QuestionType.YES_NO, order=3),
        choice=make_question(QuestionType.CHOICE, order=4, options=OPTIONS),
        comment=make_question(QuestionType.TEXT, order=5),
    )


def too_few(result):
    return isinstance(result, InsufficientData) and result.reason == Reason.TOO_FEW


def not_released(result):
    return isinstance(result, InsufficientData) and result.reason == Reason.NOT_RELEASED


def queries(call):
    with CaptureQueriesContext(connection) as captured:
        result = call()
    return result, [q["sql"] for q in captured.captured_queries]


class TestQuestionStats:
    def test_count_average_distribution_and_choice_percentages(self, setup):
        for rating, choice in [(5, "a"), (4, "a"), (4, "b"), (3, "c"), (4, "a"), (5, "a")]:
            setup.respond(rating=rating, choice=choice, agree=2)
        stats = analytics.question_stats(setup.window, setup.offering)

        rating = stats[setup.rating.pk]
        assert (rating.count, rating.average) == (6, 4.17)
        assert [(b.value, b.count) for b in rating.distribution] == [
            (1, 0),
            (2, 0),
            (3, 1),
            (4, 3),
            (5, 2),
        ]
        assert [b.percent for b in rating.distribution] == [0.0, 0.0, 16.7, 50.0, 33.3]
        assert stats[setup.agree.pk].average == 2.0

        choice = stats[setup.choice.pk]
        assert choice.average is None
        assert [(b.value, b.count, b.percent) for b in choice.distribution] == [
            ("a", 4, 66.7),
            ("b", 1, 16.7),
            ("c", 1, 16.7),
        ]
        yes_no = stats[setup.yes_no.pk]
        assert [(b.value, b.percent) for b in yes_no.distribution] == [("yes", 100.0), ("no", 0.0)]
        assert setup.comment.pk not in stats
        assert list(stats) == [setup.rating.pk, setup.agree.pk, setup.yes_no.pk, setup.choice.pk]

    def test_a_question_few_people_answered_is_hidden_on_its_own(self, setup):
        setup.respond_many(6)
        optional = make_question(QuestionType.RATING, required=False, order=9)
        for response in FeedbackResponse.objects.all()[:4]:
            Answer.objects.create(response=response, question=optional, int_value=1)
        stats = analytics.question_stats(setup.window, setup.offering)
        assert too_few(stats[optional.pk])
        assert stats[setup.rating.pk].count == 6

    def test_other_offerings_and_rounds_do_not_leak_in(self, setup):
        setup.respond_many(5, rating=5)
        other = make_offering(make_course(setup.department, code="CSE102"), setup.semester)
        setup.respond_many(5, offering=other, rating=1)
        later = make_window(setup.semester, **CLOSED)
        setup.respond_many(5, window=later, rating=2)
        stats = analytics.question_stats(setup.window, setup.offering)
        assert stats[setup.rating.pk].average == 5.0

    def test_several_offerings_form_one_slice(self, setup):
        other = make_offering(make_course(setup.department, code="CSE102"), setup.semester)
        setup.respond_many(3, rating=5)
        setup.respond_many(3, offering=other, rating=3)
        assert too_few(analytics.question_stats(setup.window, setup.offering))
        stats = analytics.question_stats(setup.window, [setup.offering, other.pk])
        assert stats[setup.rating.pk].average == 4.0


class TestCategoryScores:
    def test_mean_of_rating_and_agreement_answers_per_category(self, setup):
        setup.respond_many(6, rating=4, agree=2)
        lab, _created = QuestionCategory.objects.get_or_create(name="Lab")
        extra = make_question(QuestionType.RATING, order=8, category=lab)
        for response in FeedbackResponse.objects.all():
            Answer.objects.create(response=response, question=extra, int_value=5)
        scores = analytics.category_scores(setup.window, setup.offering)
        assert scores[setup.category.pk].average == 3.0
        assert scores[setup.category.pk].count == 12
        assert scores[lab.pk].average == 5.0
        assert list(scores) == [c.pk for c in (setup.category, lab)]

    def test_category_with_too_few_answers_is_hidden(self, setup):
        setup.respond_many(6)
        lab, _created = QuestionCategory.objects.get_or_create(name="Lab")
        extra = make_question(QuestionType.RATING, required=False, order=8, category=lab)
        for response in FeedbackResponse.objects.all()[:4]:
            Answer.objects.create(response=response, question=extra, int_value=5)
        assert too_few(analytics.category_scores(setup.window, setup.offering)[lab.pk])


class TestResponseRate:
    def enroll(self, offering, enrolled, submitted):
        students = [enrolled_student(offering) for _ in range(enrolled)]
        for student in students[:submitted]:
            SubmissionReceipt.objects.create(
                student_profile=student, offering=offering, window=self.window
            )

    def test_receipts_against_enrolled(self, setup):
        self.window = setup.window
        self.enroll(setup.offering, enrolled=8, submitted=6)
        rate = analytics.response_rate(setup.window, setup.offering)
        assert (rate.submitted, rate.enrolled, rate.percent) == (6, 8, 75.0)

    def test_too_few_receipts_hide_the_rate(self, setup):
        self.window = setup.window
        self.enroll(setup.offering, enrolled=8, submitted=4)
        assert too_few(analytics.response_rate(setup.window, setup.offering))

    def test_uses_no_response_table(self, setup):
        self.window = setup.window
        self.enroll(setup.offering, enrolled=6, submitted=5)
        _, sql = queries(lambda: analytics.response_rate(setup.window, setup.offering))
        assert not any("feedback_feedbackresponse" in q or "feedback_answer" in q for q in sql)


class TestTrend:
    def test_one_point_per_released_round_oldest_first(self, setup):
        earlier = make_window(
            setup.semester, opens=timedelta(days=-9), closes=timedelta(days=-8), name="Early"
        )
        setup.respond_many(5, window=earlier, rating=2, agree=2)
        setup.respond_many(6, rating=4, agree=4)
        points = analytics.trend(teacher=setup.offering.teacher)
        assert [(p.window_name, p.average, p.count) for p in points] == [
            ("Early", 2.0, 10),
            (setup.window.name, 4.0, 12),
        ]
        assert points[0].semester_name == setup.semester.name

    def test_rounds_below_the_threshold_or_still_open_are_left_out(self, setup):
        small = make_window(setup.semester, name="Small", **CLOSED)
        setup.respond_many(4, window=small)
        open_round = make_window(setup.semester, name="Open")
        setup.respond_many(5, window=open_round)
        setup.respond_many(5)
        points = analytics.trend(course=setup.offering.course)
        assert [p.window_name for p in points] == [setup.window.name]

    def test_nothing_qualifies(self, setup):
        setup.respond_many(4)
        assert too_few(analytics.trend(department=setup.department))

    def test_needs_a_scope(self):
        with pytest.raises(ValueError):
            analytics.trend()


class TestDepartmentAverage:
    def second_teacher_offering(self, setup):
        return make_offering(
            make_course(setup.department, code="CSE102"),
            setup.semester,
            teacher=make_teacher(setup.department),
        )

    def test_average_over_teachers_of_the_department(self, setup):
        other = self.second_teacher_offering(setup)
        setup.respond_many(3, rating=5, agree=5)
        setup.respond_many(3, offering=other, rating=3, agree=3)
        average = analytics.department_average(setup.window, setup.department)
        assert (average.average, average.count) == (4.0, 6)

    def test_one_teacher_alone_is_not_anonymous_enough(self, setup):
        setup.respond_many(8)
        assert too_few(analytics.department_average(setup.window, setup.department))

    def test_other_departments_are_ignored(self, setup):
        other = self.second_teacher_offering(setup)
        setup.respond_many(3)
        setup.respond_many(3, offering=other)
        assert too_few(analytics.department_average(setup.window, DepartmentFactory()))


class TestSentiment:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Very helpful and clear", Sentiment.POSITIVE),
            ("Boring and confusing", Sentiment.NEGATIVE),
            ("Lectures were on Monday", Sentiment.NEUTRAL),
            ("Not good at all", Sentiment.NEGATIVE),
            ("Not bad", Sentiment.POSITIVE),
            ("The lectures weren't clear", Sentiment.NEGATIVE),
            ("ক্লাস খুব ভালো ছিল", Sentiment.POSITIVE),
            ("ক্লাস ভালো না", Sentiment.NEGATIVE),
            ("পড়ানো বিরক্তিকর", Sentiment.NEGATIVE),
            ("ভালোটা বুঝিয়েছেন", Sentiment.POSITIVE),
            ("good but also boring", Sentiment.NEUTRAL),
            ("", Sentiment.NEUTRAL),
        ],
    )
    def test_tags(self, text, expected):
        assert analytics.sentiment_of(text) is expected

    def test_summary_counts_and_is_labelled_approximate(self, setup):
        for text in COMMENTS:
            setup.respond(text=text)
        summary = analytics.comment_sentiment(setup.window, setup.offering)
        assert (summary.positive, summary.neutral, summary.negative) == (3, 1, 2)
        assert summary.total == 6
        assert summary.approximate is True
        assert "Approximate" in str(analytics.APPROXIMATE_LABEL)

    def test_lexicons_do_not_overlap(self):
        assert not lexicon.POSITIVE & lexicon.NEGATIVE


class TestKeywords:
    def test_top_keywords_skip_stopwords_and_single_use_words(self, setup):
        for text in COMMENTS:
            setup.respond(text=text)
        keywords = analytics.top_keywords(setup.window, setup.offering)
        counts = {k.word: k.count for k in keywords}
        assert counts == {"lectures": 4, "clear": 2, "helpful": 2}
        assert keywords[0].word == "lectures"

    def test_word_cloud_weights_run_from_one_to_five(self, setup):
        for text in COMMENTS:
            setup.respond(text=text)
        cloud = {w.word: w.weight for w in analytics.word_cloud(setup.window, setup.offering)}
        assert cloud == {"lectures": 5, "clear": 1, "helpful": 1}

    def test_few_comments_hide_everything_even_with_many_responses(self, setup):
        setup.respond_many(4, text="Clear lectures")
        setup.respond_many(4)
        assert too_few(analytics.top_keywords(setup.window, setup.offering))
        assert too_few(analytics.word_cloud(setup.window, setup.offering))
        assert too_few(analytics.comment_sentiment(setup.window, setup.offering))

    def test_a_single_question_can_be_picked(self, setup):
        other = make_question(QuestionType.TEXT, required=False, order=7)
        for _ in range(5):
            response = setup.respond(text="Clear lectures")
            Answer.objects.create(response=response, question=other, encrypted_text="Wifi wifi")
        words = {k.word for k in analytics.top_keywords(setup.window, setup.offering, other)}
        assert words == {"wifi"}


class TestCommentList:
    def test_listed_in_stable_shuffled_order_with_tags(self, setup):
        for text in COMMENTS:
            setup.respond(text=text)
        listed = analytics.comment_list(setup.window, setup.offering, setup.comment)
        assert sorted(c.text for c in listed) == sorted(COMMENTS)
        assert listed == analytics.comment_list(setup.window, setup.offering, setup.comment)
        assert [c.text for c in listed] == anonymity.comments(
            setup.offering, setup.window, setup.comment
        )
        assert {c.text: c.sentiment for c in listed}["Boring slides, the pace is slow"] is (
            Sentiment.NEGATIVE
        )

    def test_hidden_below_the_threshold(self, setup):
        for text in COMMENTS[:4]:
            setup.respond(text=text)
        assert too_few(analytics.comment_list(setup.window, setup.offering, setup.comment))

    def test_a_filtered_slice_is_checked_too(self, setup):
        other = make_offering(make_course(setup.department, code="CSE102"), setup.semester)
        for text in COMMENTS:
            setup.respond(text=text)
        setup.respond_many(2, offering=other, text="Fine")
        assert too_few(analytics.comment_list(setup.window, other, setup.comment))


class TestRelease:
    @pytest.fixture
    def open_setup(self, setup):
        setup.window = make_window(setup.semester, name="Running")
        setup.respond_many(6, text="Clear lectures")
        return setup

    def calls(self, setup, **who):
        window, offering = setup.window, setup.offering
        return [
            analytics.question_stats(window, offering, **who),
            analytics.category_scores(window, offering, **who),
            analytics.response_rate(window, offering, **who),
            analytics.department_average(window, setup.department, **who),
            analytics.comment_sentiment(window, offering, **who),
            analytics.top_keywords(window, offering, **who),
            analytics.word_cloud(window, offering, **who),
            analytics.comment_list(window, offering, setup.comment, **who),
        ]

    def test_nothing_is_released_while_the_round_is_open(self, open_setup):
        assert all(not_released(result) for result in self.calls(open_setup))
        assert not_released(analytics.trend(teacher=open_setup.offering.teacher))

    def test_only_an_admin_with_the_live_flag_sees_an_open_round(self, open_setup):
        admin = make_admin()
        teacher = make_user("lecturer", Role.TEACHER)
        assert all(not_released(r) for r in self.calls(open_setup, viewer=admin))
        assert all(not_released(r) for r in self.calls(open_setup, viewer=teacher, live=True))
        assert all(not_released(r) for r in self.calls(open_setup, live=True))
        stats = analytics.question_stats(
            open_setup.window, open_setup.offering, viewer=admin, live=True
        )
        assert stats[open_setup.rating.pk].count == 6
        trend = analytics.trend(teacher=open_setup.offering.teacher, viewer=admin, live=True)
        assert trend[0].count == 12

    def test_the_live_flag_does_not_lift_the_threshold(self, setup):
        window = make_window(setup.semester, name="Running")
        setup.respond_many(4, window=window)
        admin = make_admin()
        assert too_few(analytics.question_stats(window, setup.offering, viewer=admin, live=True))
        assert too_few(
            analytics.comment_list(window, setup.offering, setup.comment, viewer=admin, live=True)
        )

    def test_released_the_moment_the_round_closes(self, open_setup):
        closes = open_setup.window.closes_at
        before, after = closes - timedelta(seconds=1), closes
        assert not_released(
            analytics.question_stats(open_setup.window, open_setup.offering, now=before)
        )
        stats = analytics.question_stats(open_setup.window, open_setup.offering, now=after)
        assert stats[open_setup.rating.pk].count == 6

    def test_a_closed_round_needs_no_flag(self, setup):
        setup.respond_many(6, text="Clear lectures")
        assert not any(isinstance(r, InsufficientData) for r in self.calls_ready(setup))

    def calls_ready(self, setup):
        enrolled = [enrolled_student(setup.offering) for _ in range(5)]
        for student in enrolled:
            SubmissionReceipt.objects.create(
                student_profile=student, offering=setup.offering, window=setup.window
            )
        other = make_offering(
            make_course(setup.department, code="CSE103"),
            setup.semester,
            teacher=make_teacher(setup.department),
        )
        setup.respond_many(3, offering=other)
        return self.calls(setup)


class TestThreshold:
    def test_every_function_hides_below_the_threshold(self, setup):
        setup.respond_many(4, text="Clear lectures")
        window, offering = setup.window, setup.offering
        results = [
            analytics.question_stats(window, offering),
            analytics.category_scores(window, offering),
            analytics.response_rate(window, offering),
            analytics.department_average(window, setup.department),
            analytics.comment_sentiment(window, offering),
            analytics.top_keywords(window, offering),
            analytics.word_cloud(window, offering),
            analytics.comment_list(window, offering, setup.comment),
            analytics.trend(teacher=offering.teacher),
        ]
        assert all(too_few(result) for result in results)

    def test_the_threshold_follows_the_setting_and_its_floor(self, setup, settings):
        setup.respond_many(3)
        settings.MIN_RESPONSES = 3
        assert not too_few(analytics.question_stats(setup.window, setup.offering))
        settings.MIN_RESPONSES = 1
        analytics.invalidate(setup.window)
        assert anonymity.min_responses() == 3
        assert not too_few(analytics.question_stats(setup.window, setup.offering))
        settings.MIN_RESPONSES = 4
        analytics.invalidate(setup.window)
        assert too_few(analytics.question_stats(setup.window, setup.offering))

    def test_a_slice_is_checked_on_its_own_not_by_the_round_total(self, setup):
        other = make_offering(make_course(setup.department, code="CSE102"), setup.semester)
        setup.respond_many(8)
        setup.respond_many(2, offering=other)
        assert not too_few(analytics.question_stats(setup.window, setup.offering))
        assert too_few(analytics.question_stats(setup.window, other))
        assert too_few(analytics.question_stats(setup.window, []))

    def test_insufficient_data_carries_no_count(self):
        result = InsufficientData(Reason.TOO_FEW)
        assert vars(result) == {"reason": Reason.TOO_FEW}
        assert str(result.message) == "Not enough responses to show this."
        assert "closes" in str(InsufficientData(Reason.NOT_RELEASED).message)


class TestCache:
    def test_second_call_reads_the_cache(self, setup):
        setup.respond_many(6, text="Clear lectures")
        window, offering = setup.window, setup.offering
        calls = [
            lambda: analytics.question_stats(window, offering),
            lambda: analytics.category_scores(window, offering),
            lambda: analytics.response_rate(window, offering),
            lambda: analytics.department_average(window, setup.department),
            lambda: analytics.comment_sentiment(window, offering),
            lambda: analytics.top_keywords(window, offering),
        ]
        for call in calls:
            first = call()
            with CaptureQueriesContext(connection) as again:
                assert call() == first
            assert len(again) == 0

    def test_a_new_response_invalidates_the_round(self, setup):
        setup.respond_many(5)
        before = analytics.question_stats(setup.window, setup.offering)[setup.rating.pk]
        setup.respond(rating=1)
        assert analytics.question_stats(setup.window, setup.offering)[setup.rating.pk] == before
        analytics.invalidate(setup.window)
        after = analytics.question_stats(setup.window, setup.offering)[setup.rating.pk]
        assert after.count == 6
        assert after.average < before.average

    def test_other_rounds_stay_cached(self, setup):
        later = make_window(setup.semester, **CLOSED)
        setup.respond_many(5, window=later)
        analytics.question_stats(later, setup.offering)
        analytics.invalidate(setup.window)
        with CaptureQueriesContext(connection) as captured:
            analytics.question_stats(later, setup.offering)
        assert len(captured) == 0

    def test_submitting_feedback_invalidates(self, setup, django_capture_on_commit_callbacks):
        from apps.feedback.services.submit import submit_feedback

        setup.respond_many(5)
        window = make_window(setup.semester, name="Live", opens=timedelta(hours=-1))
        admin = make_admin()
        setup.respond_many(5, window=window)
        live = {"viewer": admin, "live": True}
        assert analytics.question_stats(window, setup.offering, **live)[setup.rating.pk].count == 5

        student = enrolled_student(setup.offering)
        answers = {
            setup.rating.pk: 3,
            setup.agree.pk: 3,
            setup.yes_no.pk: "yes",
            setup.choice.pk: "a",
            setup.comment.pk: "Fine lectures",
        }
        with django_capture_on_commit_callbacks(execute=True):
            submit_feedback(student, setup.offering, window, answers, reauth_ok=True)
        assert analytics.question_stats(window, setup.offering, **live)[setup.rating.pk].count == 6

    def test_saving_a_round_invalidates_it(self, setup, django_capture_on_commit_callbacks):
        from apps.feedback.forms import WindowForm
        from apps.feedback.services import windows

        setup.respond_many(5)
        analytics.question_stats(setup.window, setup.offering)
        key = analytics._version_key(setup.window.pk)
        version = cache.get(key)
        form = WindowForm(
            {
                "semester": setup.semester.pk,
                "name": "Renamed",
                "opens_at": setup.window.opens_at.astimezone().strftime("%Y-%m-%d %H:%M"),
                "closes_at": setup.window.closes_at.astimezone().strftime("%Y-%m-%d %H:%M"),
                "is_active": "on",
            },
            instance=setup.window,
        )
        assert form.is_valid(), form.errors
        with django_capture_on_commit_callbacks(execute=True):
            windows.save_window(form, actor=make_admin())
        assert cache.get(key) != version


class TestQueries:
    def test_query_counts_when_computing_and_when_cached(self, setup):
        setup.respond_many(6, text="Clear lectures")
        other = make_offering(
            make_course(setup.department, code="CSE102"),
            setup.semester,
            teacher=make_teacher(setup.department),
        )
        setup.respond_many(3, offering=other)
        for student in [enrolled_student(setup.offering) for _ in range(5)]:
            SubmissionReceipt.objects.create(
                student_profile=student, offering=setup.offering, window=setup.window
            )
        window, offering = setup.window, setup.offering
        counted = [
            (lambda: analytics.question_stats(window, offering), 3),
            (lambda: analytics.response_rate(window, offering), 2),
            (lambda: analytics.department_average(window, setup.department), 2),
            (lambda: analytics.comment_sentiment(window, offering), 2),
            (lambda: analytics.comment_list(window, offering, setup.comment), 2),
            (lambda: analytics.trend(teacher=offering.teacher), 3),
        ]
        for call, expected in counted:
            _, sql = queries(call)
            assert len(sql) == expected, sql

    def test_query_count_does_not_grow_with_the_number_of_responses(self, setup):
        setup.respond_many(5, text="Clear lectures")
        _, few = queries(lambda: analytics.question_stats(setup.window, setup.offering))
        cache.clear()
        setup.respond_many(40, text="Clear lectures")
        _, many = queries(lambda: analytics.question_stats(setup.window, setup.offering))
        assert len(few) == len(many)

    def test_no_query_joins_a_response_to_a_person(self, setup):
        other = make_offering(
            make_course(setup.department, code="CSE102"),
            setup.semester,
            teacher=make_teacher(setup.department),
        )
        setup.respond_many(6, text="Clear lectures")
        setup.respond_many(3, offering=other, text="Boring")
        student = make_student(setup.department)
        Enrollment.objects.create(student_profile=student, offering=setup.offering)
        window, offering = setup.window, setup.offering
        everything = [
            lambda: analytics.question_stats(window, offering),
            lambda: analytics.category_scores(window, offering),
            lambda: analytics.response_rate(window, offering),
            lambda: analytics.department_average(window, setup.department),
            lambda: analytics.comment_sentiment(window, offering),
            lambda: analytics.top_keywords(window, offering),
            lambda: analytics.word_cloud(window, offering),
            lambda: analytics.comment_list(window, offering, setup.comment),
            lambda: analytics.trend(department=setup.department),
        ]
        sql = []
        for call in everything:
            sql += queries(call)[1]
        assert sql
        people = ("accounts_", "submissionreceipt", "enrollment_enrollment")
        for statement in sql:
            if "feedback_feedbackresponse" in statement or "feedback_answer" in statement:
                assert not any(table in statement for table in people), statement


def test_offering_ids_accepts_models_ids_and_iterables(setup):
    other = make_offering(make_course(setup.department, code="CSE102"), setup.semester)
    assert analytics.offering_ids(setup.offering) == (setup.offering.pk,)
    assert analytics.offering_ids(other.pk) == (other.pk,)
    assert analytics.offering_ids([other, setup.offering.pk, other.pk]) == tuple(
        sorted({setup.offering.pk, other.pk})
    )
    assert analytics.offering_ids(CourseOffering.objects.none()) == ()
