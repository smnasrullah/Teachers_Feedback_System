import threading
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import timedelta
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from django.apps import apps
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.sessions.backends.db import SessionStore
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import connection, models
from django.db.models.functions import Cast
from django.utils import timezone, translation

from apps.academics.models import CourseOffering, CourseType
from apps.accounts.models import StudentProfile, User
from apps.auditlog.models import AuditEvent
from apps.core.services.keys import rotate_encrypted_fields
from apps.enrollment.models import Enrollment
from apps.feedback.models import (
    Answer,
    AppliesTo,
    Draft,
    FeedbackResponse,
    FeedbackWindow,
    Question,
    QuestionType,
    SubmissionReceipt,
)
from apps.feedback.services import anonymity, drafts, proxy
from apps.feedback.services import filter as text_filter
from apps.feedback.services.eligibility import Rejection, SubmissionRejected
from apps.feedback.services.submit import TEXT_MAX_LENGTH, submit_feedback
from tests.factories import PASSWORD, DepartmentFactory, LevelTermFactory, claim, make_student
from tests.test_academics import make_course, make_offering, make_semester

pytestmark = pytest.mark.django_db

ANONYMOUS = {FeedbackResponse, Answer}
# Every response of an offering shares these rows by design. Walking on from them reaches the
# whole class (its enrollments), which identifies a group, never the writer of one response.
SHARED = {CourseOffering, FeedbackWindow, Question}
IDENTIFYING = {User, StudentProfile, Enrollment, SubmissionReceipt}


@pytest.fixture(autouse=True)
def _english():
    with translation.override("en"):
        yield


def make_window(semester, *, opens=timedelta(hours=-1), closes=timedelta(days=1), **fields):
    now = timezone.now()
    return FeedbackWindow.objects.create(
        semester=semester,
        name=fields.pop("name", f"Round {FeedbackWindow.objects.count() + 1}"),
        opens_at=now + opens,
        closes_at=now + closes,
        **fields,
    )


def make_question(question_type, *, required=True, **fields):
    return Question.objects.create(
        text=fields.pop("text", f"Question {Question.objects.count() + 1}"),
        question_type=question_type,
        required=required,
        **fields,
    )


def enrolled_student(offering, password=None):
    student = make_student(offering.course.department)
    claim(student, password)
    Enrollment.objects.create(student_profile=student, offering=offering)
    return student


@dataclass
class Round:
    offering: CourseOffering
    window: FeedbackWindow
    student: StudentProfile
    rating: Question
    agree: Question
    choice: Question
    yes_no: Question
    comment: Question
    remark: Question
    lab_only: Question

    def answers(self, **overrides) -> dict:
        values = {
            "rating": "4",
            "agree": 5,
            "choice": "b",
            "yes_no": True,
            "comment": "  Clear lectures, more examples please.  ",
            "remark": "",
            **overrides,
        }
        return {getattr(self, name).pk: value for name, value in values.items()}

    def submit(self, *, student=None, offering=None, window=None, answers=None, reauth_ok=True):
        return submit_feedback(
            student or self.student,
            offering or self.offering,
            window or self.window,
            self.answers() if answers is None else answers,
            reauth_ok=reauth_ok,
        )


@pytest.fixture
def world():
    department = DepartmentFactory()
    semester = make_semester(current=True)
    offering = make_offering(make_course(department, course_type=CourseType.THEORY), semester)
    options = [{"value": value, "en": value.upper(), "bn": value} for value in ("a", "b", "c")]
    return Round(
        offering=offering,
        window=make_window(semester),
        student=enrolled_student(offering),
        rating=make_question(QuestionType.RATING, order=1),
        agree=make_question(QuestionType.LIKERT, order=2),
        choice=make_question(QuestionType.CHOICE, order=3, options=options),
        yes_no=make_question(QuestionType.YES_NO, order=4, required=False),
        comment=make_question(QuestionType.TEXT, order=5),
        remark=make_question(QuestionType.TEXT, order=6, required=False),
        lab_only=make_question(QuestionType.RATING, order=7, applies_to=AppliesTo.LAB),
    )


def rejection(excinfo) -> Rejection:
    return excinfo.value.reason


def nothing_stored():
    return not (
        SubmissionReceipt.objects.exists()
        or FeedbackResponse.objects.exists()
        or Answer.objects.exists()
    )


def identifying_path(start: set) -> str | None:
    """Walk every forward and reverse relation from ``start`` (not past ``SHARED``) and
    return the first chain that reaches an ``IDENTIFYING`` model."""
    paths = {model: [model.__name__] for model in start}
    queue = deque(start)
    while queue:
        model = queue.popleft()
        for field in model._meta.get_fields(include_hidden=True):
            if not field.is_relation:
                continue
            path = [*paths[model], field.name]
            target = field.related_model
            if target is None or target in IDENTIFYING:
                return " -> ".join([*path, getattr(target, "__name__", "<generic>")])
            if target not in paths and target not in SHARED:
                paths[target] = [*path, target.__name__]
                queue.append(target)
    return None


class TestAnonymousStructure:
    def test_no_relation_chain_from_anonymous_rows_to_a_person(self):
        assert identifying_path(ANONYMOUS) is None

    def test_the_walk_finds_a_chain_where_one_exists(self):
        assert identifying_path({Draft}) == "Draft -> student_profile -> StudentProfile"

    def test_anonymous_rows_link_only_to_offering_round_and_question(self):
        for model in ANONYMOUS:
            targets = {
                field.related_model
                for field in model._meta.get_fields(include_hidden=True)
                if field.is_relation
            }
            assert targets <= ANONYMOUS | SHARED, model

    def test_no_model_points_at_anonymous_rows_except_answers(self):
        for model in apps.get_models(include_auto_created=True):
            for field in model._meta.get_fields(include_hidden=True):
                assert not isinstance(field, GenericForeignKey), (
                    f"{model.__name__}.{field.name} could point at an anonymous row"
                )
                forward = field.is_relation and (
                    field.concrete or (field.many_to_many and not field.auto_created)
                )
                if forward and field.related_model in ANONYMOUS:
                    assert model in ANONYMOUS, f"{model.__name__}.{field.name}"

    @pytest.mark.parametrize("model", sorted(ANONYMOUS, key=lambda model: model.__name__))
    def test_no_time_ip_or_ordered_key(self, model):
        dated = (models.DateField, models.TimeField, models.DurationField)
        for field in model._meta.concrete_fields:
            assert not isinstance(field, dated), field.name
            assert not isinstance(field, models.GenericIPAddressField), field.name
        pk = model._meta.pk
        assert isinstance(pk, models.UUIDField)
        assert pk.default is uuid.uuid4

    def test_receipt_holds_no_content_and_no_time(self):
        names = {field.name for field in SubmissionReceipt._meta.concrete_fields}
        assert names == {"id", "student_profile", "offering", "window"}

    def test_comment_ciphertext_carries_no_time_even_after_key_rotation(self, world, settings):
        world.submit()
        raw = Answer.objects.annotate(raw=Cast("encrypted_text", models.TextField())).get(
            question=world.comment
        )
        assert Fernet(settings.FIELD_ENCRYPTION_KEYS[0]).extract_timestamp(raw.raw.encode()) == 0
        new_key = Fernet.generate_key().decode()
        settings.FIELD_ENCRYPTION_KEYS = [new_key, *settings.FIELD_ENCRYPTION_KEYS]
        rotate_encrypted_fields()
        rotated = Answer.objects.annotate(raw=Cast("encrypted_text", models.TextField())).get(
            question=world.comment
        )
        assert rotated.raw != raw.raw
        assert Fernet(new_key).extract_timestamp(rotated.raw.encode()) == 0

    def test_draft_ciphertext_is_ordinary(self, world, settings):
        drafts.save_draft(world.student, world.offering, world.window, {world.rating.pk: 3})
        raw = Draft.objects.annotate(raw=Cast("payload", models.TextField())).get()
        stamp = Fernet(settings.FIELD_ENCRYPTION_KEYS[0]).extract_timestamp(raw.raw.encode())
        assert stamp > 0


class TestSubmit:
    def test_stores_one_anonymous_response(self, world):
        receipt = world.submit()
        assert receipt.student_profile == world.student
        response = FeedbackResponse.objects.get()
        assert (response.offering, response.window) == (world.offering, world.window)
        stored = {answer.question_id: answer for answer in response.answers.all()}
        assert set(stored) == {
            world.rating.pk,
            world.agree.pk,
            world.choice.pk,
            world.yes_no.pk,
            world.comment.pk,
        }
        assert stored[world.rating.pk].int_value == 4
        assert stored[world.agree.pk].int_value == 5
        assert stored[world.choice.pk].choice_value == "b"
        assert stored[world.yes_no.pk].choice_value == "yes"
        assert stored[world.comment.pk].encrypted_text == "Clear lectures, more examples please."

    def test_bangla_digits_are_a_rating(self, world):
        world.submit(answers=world.answers(rating="৩"))
        assert Answer.objects.get(question=world.rating).int_value == 3

    def test_second_submit_is_refused_and_stores_nothing_more(self, world):
        world.submit()
        with pytest.raises(SubmissionRejected) as excinfo:
            world.submit(answers=world.answers(rating=1))
        assert rejection(excinfo) == Rejection.ALREADY_SUBMITTED
        assert SubmissionReceipt.objects.count() == 1
        assert FeedbackResponse.objects.count() == 1
        assert Answer.objects.get(question=world.rating).int_value == 4

    def test_a_new_round_takes_new_feedback(self, world):
        world.submit()
        world.submit(window=make_window(world.offering.semester))
        assert FeedbackResponse.objects.count() == 2

    def test_without_a_fresh_reauth_nothing_is_stored(self, world):
        with pytest.raises(SubmissionRejected) as excinfo:
            world.submit(reauth_ok=False)
        assert rejection(excinfo) == Rejection.REAUTH_REQUIRED
        assert nothing_stored()

    @pytest.mark.parametrize(
        "window_fields",
        [
            {"opens": timedelta(days=-3), "closes": timedelta(seconds=-1)},
            {"opens": timedelta(hours=1), "closes": timedelta(days=1)},
            {"is_active": False},
        ],
        ids=["closed", "upcoming", "inactive"],
    )
    def test_window_must_be_open(self, world, window_fields):
        window = make_window(world.offering.semester, **window_fields)
        with pytest.raises(SubmissionRejected) as excinfo:
            world.submit(window=window)
        assert rejection(excinfo) == Rejection.WINDOW_CLOSED
        assert nothing_stored()

    def test_window_closing_meanwhile_is_read_from_the_database(self, world):
        FeedbackWindow.objects.filter(pk=world.window.pk).update(
            closes_at=timezone.now() - timedelta(seconds=1)
        )
        with pytest.raises(SubmissionRejected) as excinfo:
            world.submit()
        assert rejection(excinfo) == Rejection.WINDOW_CLOSED

    def test_window_of_another_semester_is_out_of_scope(self, world):
        window = make_window(make_semester(name="Fall 2026"))
        with pytest.raises(SubmissionRejected) as excinfo:
            world.submit(window=window)
        assert rejection(excinfo) == Rejection.OUT_OF_SCOPE
        assert nothing_stored()

    def test_round_for_another_department_is_out_of_scope(self, world):
        world.window.departments.set([DepartmentFactory()])
        with pytest.raises(SubmissionRejected) as excinfo:
            world.submit()
        assert rejection(excinfo) == Rejection.OUT_OF_SCOPE
        world.window.departments.add(world.offering.course.department)
        world.submit()

    def test_round_for_another_level_term_is_out_of_scope(self, world):
        world.window.level_terms.set([LevelTermFactory()])
        with pytest.raises(SubmissionRejected) as excinfo:
            world.submit()
        assert rejection(excinfo) == Rejection.OUT_OF_SCOPE
        world.window.level_terms.add(world.offering.course.level_term)
        world.submit()

    def test_course_not_enrolled_in_is_refused(self, world):
        other = make_offering(
            make_course(world.offering.course.department, code="CSE999"), world.offering.semester
        )
        with pytest.raises(SubmissionRejected) as excinfo:
            world.submit(offering=other)
        assert rejection(excinfo) == Rejection.NOT_ENROLLED
        assert nothing_stored()

    def test_other_department_course_not_enrolled_in_is_refused(self, world):
        other = make_offering(make_course(DepartmentFactory()), world.offering.semester)
        with pytest.raises(SubmissionRejected) as excinfo:
            world.submit(offering=other)
        assert rejection(excinfo) == Rejection.NOT_ENROLLED

    def test_every_missing_required_answer_is_reported(self, world):
        answers = world.answers(rating="", comment="   ")
        del answers[world.choice.pk]
        with pytest.raises(ValidationError) as excinfo:
            world.submit(answers=answers)
        errors = excinfo.value.error_dict
        assert set(errors) == {world.rating.pk, world.choice.pk, world.comment.pk}
        assert {error.code for error in errors[world.rating.pk]} == {"required"}
        assert nothing_stored()

    def test_optional_questions_may_stay_unanswered(self, world):
        answers = world.answers()
        del answers[world.yes_no.pk], answers[world.remark.pk]
        world.submit(answers=answers)
        assert not Answer.objects.filter(question__in=[world.yes_no, world.remark]).exists()

    @pytest.mark.parametrize("value", [0, 6, "7", "-1", "3.5", 3.5, "four", True, ["4"]])
    @pytest.mark.parametrize("name", ["rating", "agree"])
    def test_scale_answers_must_be_one_to_five(self, world, name, value):
        with pytest.raises(ValidationError) as excinfo:
            world.submit(answers=world.answers(**{name: value}))
        question = getattr(world, name)
        assert [error.code for error in excinfo.value.error_dict[question.pk]] == ["out_of_range"]
        assert nothing_stored()

    @pytest.mark.parametrize(
        ("name", "value"), [("choice", "z"), ("choice", 1), ("yes_no", "maybe")]
    )
    def test_choices_must_be_offered(self, world, name, value):
        with pytest.raises(ValidationError) as excinfo:
            world.submit(answers=world.answers(**{name: value}))
        assert [error.code for error in excinfo.value.error_dict[getattr(world, name).pk]] == [
            "invalid_choice"
        ]

    @pytest.mark.parametrize("name", ["lab_only", "inactive"])
    def test_answers_to_questions_not_on_the_form_are_refused(self, world, name):
        if name == "inactive":
            world.lab_only.applies_to = AppliesTo.ALL
            world.lab_only.is_active = False
            world.lab_only.save()
        answers = {**world.answers(), world.lab_only.pk: 3}
        with pytest.raises(ValidationError) as excinfo:
            world.submit(answers=answers)
        assert [error.code for error in excinfo.value.error_dict[NON_FIELD_ERRORS]] == [
            "stale_form"
        ]
        assert nothing_stored()

    def test_lab_questions_apply_to_lab_courses(self, world):
        lab = make_offering(
            make_course(world.offering.course.department, code="CSE102", course_type="lab"),
            world.offering.semester,
        )
        Enrollment.objects.create(student_profile=world.student, offering=lab)
        world.submit(offering=lab, answers={**world.answers(), world.lab_only.pk: 2})
        assert Answer.objects.get(question=world.lab_only).int_value == 2

    def test_text_longer_than_the_limit_is_refused(self, world):
        with pytest.raises(ValidationError) as excinfo:
            world.submit(answers=world.answers(comment="x" * (TEXT_MAX_LENGTH + 1)))
        assert [error.code for error in excinfo.value.error_dict[world.comment.pk]] == [
            "max_length"
        ]

    def test_text_goes_through_the_filter(self, world, monkeypatch):
        monkeypatch.setattr(
            text_filter, "clean", lambda text: text_filter.CleanResult(text.replace("bad ", ""))
        )
        world.submit(answers=world.answers(comment="a bad teacher"))
        assert Answer.objects.get(question=world.comment).encrypted_text == "a teacher"

    def test_required_text_emptied_by_the_filter_is_a_field_error(self, world, monkeypatch):
        monkeypatch.setattr(text_filter, "clean", lambda text: text_filter.CleanResult(""))
        with pytest.raises(ValidationError) as excinfo:
            world.submit()
        assert [error.code for error in excinfo.value.error_dict[world.comment.pk]] == [
            "cleaned_empty"
        ]
        assert nothing_stored()

    def test_optional_text_emptied_by_the_filter_is_dropped(self, world, monkeypatch):
        def drop_names(text):
            return text_filter.CleanResult("" if "Rahim" in text else text)

        monkeypatch.setattr(text_filter, "clean", drop_names)
        world.submit(answers=world.answers(remark="Rahim"))
        assert not Answer.objects.filter(question=world.remark).exists()
        assert Answer.objects.filter(question=world.comment).exists()

    def test_submit_deletes_the_draft(self, world):
        drafts.save_draft(world.student, world.offering, world.window, {world.rating.pk: 2})
        world.submit()
        assert not Draft.objects.exists()

    def test_audit_records_the_submission_without_content_or_response(self, world):
        world.submit()
        event = AuditEvent.objects.get(action="feedback.submitted")
        response = FeedbackResponse.objects.get()
        assert event.actor_id == world.student.registry.claimed_by_id
        assert (event.object_type, event.object_id) == (
            "academics.courseoffering",
            str(world.offering.pk),
        )
        assert event.metadata == {"window_id": world.window.pk}
        dump = repr(AuditEvent.objects.values().get(pk=event.pk))
        assert str(response.pk) not in dump
        assert "lectures" not in dump

    def test_rejections_are_audited_with_the_reason(self, world):
        world.submit()
        with pytest.raises(SubmissionRejected):
            world.submit()
        event = AuditEvent.objects.get(action="feedback.submit_rejected")
        assert event.metadata == {"window_id": world.window.pk, "reason": "already_submitted"}

    def test_field_errors_leave_no_audit_trail(self, world):
        with pytest.raises(ValidationError):
            world.submit(answers=world.answers(rating=9))
        assert not AuditEvent.objects.filter(action__startswith="feedback.").exists()


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
def test_parallel_submits_store_exactly_one_response(world):
    workers = 6
    barrier = threading.Barrier(workers)
    outcomes = []

    def attempt():
        try:
            barrier.wait()
            world.submit()
            outcomes.append("stored")
        except SubmissionRejected as exc:
            outcomes.append(exc.reason)
        except Exception as exc:  # reported by the assertion below
            outcomes.append(repr(exc))
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(outcomes) == sorted(["stored"] + [Rejection.ALREADY_SUBMITTED] * (workers - 1))
    assert SubmissionReceipt.objects.count() == 1
    assert FeedbackResponse.objects.count() == 1


class TestDrafts:
    def test_round_trip_is_encrypted_and_filtered(self, world):
        drafts.save_draft(
            world.student,
            world.offering,
            world.window,
            {world.rating.pk: 4, world.comment.pk: "half a thought", world.lab_only.pk: 1},
        )
        raw = Draft.objects.annotate(raw=Cast("payload", models.TextField())).get()
        assert "half a thought" not in raw.raw
        loaded = drafts.load_draft(world.student, world.offering, world.window)
        assert loaded == {world.rating.pk: 4, world.comment.pk: "half a thought"}

    def test_saving_again_replaces_the_draft(self, world):
        drafts.save_draft(world.student, world.offering, world.window, {world.rating.pk: 4})
        drafts.save_draft(world.student, world.offering, world.window, {world.rating.pk: 5})
        assert Draft.objects.count() == 1
        assert drafts.load_draft(world.student, world.offering, world.window) == {
            world.rating.pk: 5
        }

    def test_drafts_belong_to_their_owner(self, world):
        drafts.save_draft(world.student, world.offering, world.window, {world.rating.pk: 4})
        classmate = enrolled_student(world.offering)
        assert drafts.load_draft(classmate, world.offering, world.window) == {}

    def test_no_draft_after_submitting(self, world):
        world.submit()
        with pytest.raises(SubmissionRejected) as excinfo:
            drafts.save_draft(world.student, world.offering, world.window, {world.rating.pk: 1})
        assert rejection(excinfo) == Rejection.ALREADY_SUBMITTED
        assert not Draft.objects.exists()

    def test_no_draft_when_not_enrolled(self, world):
        outsider = make_student(world.offering.course.department)
        with pytest.raises(SubmissionRejected) as excinfo:
            drafts.save_draft(outsider, world.offering, world.window, {world.rating.pk: 1})
        assert rejection(excinfo) == Rejection.NOT_ENROLLED


class TestAnonymityRules:
    @pytest.mark.parametrize(("configured", "effective"), [(1, 3), (3, 3), (5, 5), (8, 8)])
    def test_threshold_never_drops_below_the_floor(self, settings, configured, effective):
        settings.MIN_RESPONSES = configured
        assert anonymity.min_responses() == effective
        assert not anonymity.enough_responses(effective - 1)
        assert anonymity.enough_responses(effective)

    def test_results_only_after_the_round_closes(self, world):
        assert not anonymity.results_visible(world.window)
        assert not anonymity.results_visible(
            world.window, world.window.closes_at - timedelta(microseconds=1)
        )
        assert anonymity.results_visible(world.window, world.window.closes_at)

    def test_shuffle_is_stable_and_unrelated_to_insertion_order(self, world):
        items = [SimpleNamespace(pk=uuid.UUID(int=n)) for n in range(40)]
        order = anonymity.stable_shuffle(items, offering=world.offering, window=world.window)
        again = anonymity.stable_shuffle(
            reversed(items), offering=world.offering, window=world.window
        )
        assert order == again
        assert order != items
        elsewhere = anonymity.stable_shuffle(
            items, offering=world.offering, window=make_window(world.offering.semester)
        )
        assert elsewhere != order

    def _closed_round_with_comments(self, world, count):
        window = make_window(
            world.offering.semester, opens=timedelta(days=-5), closes=timedelta(days=-1)
        )
        for n in range(count):
            response = FeedbackResponse.objects.create(offering=world.offering, window=window)
            Answer.objects.create(response=response, question=world.comment, encrypted_text=f"c{n}")
        return window

    def test_comments_hidden_below_the_threshold(self, world, settings):
        settings.MIN_RESPONSES = 5
        window = self._closed_round_with_comments(world, 4)
        assert anonymity.comments(world.offering, window, world.comment) is None

    def test_comments_listed_once_closed_and_enough(self, world, settings):
        settings.MIN_RESPONSES = 5
        window = self._closed_round_with_comments(world, 5)
        listed = anonymity.comments(world.offering, window, world.comment)
        assert sorted(listed) == [f"c{n}" for n in range(5)]
        assert listed == anonymity.comments(world.offering, window, world.comment)

    def test_comments_hidden_while_the_round_is_open(self, world, settings):
        settings.MIN_RESPONSES = 3
        for _ in range(3):
            world.submit(student=enrolled_student(world.offering))
        assert anonymity.comments(world.offering, world.window, world.comment) is None


def signed_in_request(rf, user):
    request = rf.post("/feedback/submit/")
    request.user = user
    request.session = SessionStore()
    return request


class TestProxyPrevention:
    @pytest.fixture
    def user(self, world):
        student = enrolled_student(world.offering, password=PASSWORD)
        return student.registry.claimed_by

    def test_fresh_after_the_right_password_for_five_minutes(self, rf, user):
        request = signed_in_request(rf, user)
        assert not proxy.reauth_is_fresh(request)
        assert proxy.reauthenticate(request, PASSWORD) == proxy.ReauthOutcome.OK
        assert proxy.reauth_is_fresh(request)
        request.session[proxy.REAUTH_KEY] -= proxy.REAUTH_MAX_AGE
        assert proxy.reauth_is_fresh(request)
        request.session[proxy.REAUTH_KEY] -= 1
        assert not proxy.reauth_is_fresh(request)
        event = AuditEvent.objects.get(action="feedback.reauth")
        assert event.actor_id == user.pk
        assert event.metadata == {"outcome": "ok"}

    def test_wrong_password_clears_freshness_and_is_audited(self, rf, user):
        request = signed_in_request(rf, user)
        proxy.reauthenticate(request, PASSWORD)
        assert proxy.reauthenticate(request, "not-the-password") == (proxy.ReauthOutcome.REJECTED)
        assert not proxy.reauth_is_fresh(request)
        outcomes = AuditEvent.objects.filter(action="feedback.reauth").values_list(
            "metadata__outcome", flat=True
        )
        assert sorted(outcomes) == ["ok", "rejected"]
        assert "not-the-password" not in repr(list(AuditEvent.objects.values()))

    def test_wrong_passwords_lock_the_account(self, rf, user, settings):
        request = signed_in_request(rf, user)
        for _ in range(settings.AXES_FAILURE_LIMIT):
            proxy.reauthenticate(request, "wrong-password")
        assert proxy.reauthenticate(request, PASSWORD) == proxy.ReauthOutcome.LOCKED
        assert not proxy.reauth_is_fresh(request)

    def test_reauth_is_rate_limited(self, rf, user, monkeypatch):
        monkeypatch.setattr(proxy, "REAUTH_RATES", (("user", "2/10m"),))
        request = signed_in_request(rf, user)
        proxy.reauthenticate(request, "wrong-password")
        proxy.reauthenticate(request, "wrong-password")
        assert proxy.reauthenticate(request, PASSWORD) == proxy.ReauthOutcome.THROTTLED
        assert not proxy.reauth_is_fresh(request)

    def test_submissions_are_rate_limited_and_audited(self, rf, user):
        request = signed_in_request(rf, user)
        allowed = int(proxy.SUBMIT_RATES[0][1].split("/")[0])
        assert not any(proxy.submit_throttled(request) for _ in range(allowed))
        assert proxy.submit_throttled(request)
        event = AuditEvent.objects.get(action="feedback.submit_throttled")
        assert event.actor_id == user.pk
