from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone, translation

from apps.academics.models import CourseType
from apps.auditlog.models import AuditEvent
from apps.feedback.forms import WindowForm
from apps.feedback.models import (
    Answer,
    AppliesTo,
    FeedbackResponse,
    FeedbackWindow,
    Question,
    QuestionCategory,
    QuestionType,
    WindowStatus,
)
from apps.feedback.services import eligibility, question_bank, questions, windows
from apps.feedback.services.eligibility import Rejection, SubmissionRejected
from apps.feedback.services.submit import clean_answers
from tests.factories import DepartmentFactory, LevelTermFactory, make_admin, sign_in
from tests.test_academics import make_course, make_offering, make_semester
from tests.test_feedback_core import enrolled_student, make_question, make_window

pytestmark = pytest.mark.django_db

HEADER = (
    "| # | Category | Question (English) | প্রশ্ন (বাংলা) | Type | Required | Applies "
    "| Options (EN) | বিকল্প (বাংলা) |\n|---|---|---|---|---|---|---|---|---|\n"
)


@pytest.fixture(autouse=True)
def _english():
    with translation.override("en"):
        yield


@pytest.fixture
def admin():
    return make_admin()


def bank(*rows: str) -> str:
    return "# Question Bank\n\n" + HEADER + "\n".join(rows) + "\n"


def actions() -> set[str]:
    return set(AuditEvent.objects.values_list("action", flat=True))


def at(hour=0, minute=0, second=0) -> datetime:
    return datetime(2030, 3, 1, hour, minute, second, tzinfo=UTC)


class TestParser:
    def test_reads_bangla_and_escaped_pipes(self):
        parsed = question_bank.parse(
            bank(
                r"| 1 | Teaching | Rate A \| B clearly. | শিক্ষক বিষয়বস্তু স্পষ্টভাবে বোঝান। "
                "| rating | yes | all |  |  |",
                "| 2 | Lab | Lab equipment was sufficient. | ল্যাবের সরঞ্জাম যথেষ্ট ছিল। "
                "| choice | no | lab | Yes / Partly / No | হ্যাঁ / আংশিক / না |",
            )
        )
        first, second = parsed.questions
        assert not parsed.skipped
        assert first.text == "Rate A | B clearly."
        assert first.text_bn == "শিক্ষক বিষয়বস্তু স্পষ্টভাবে বোঝান।"
        assert second.options == (("Yes", "হ্যাঁ"), ("Partly", "আংশিক"), ("No", "না"))
        assert (second.required, second.applies_to) == (False, "lab")

    def test_code_block_example_and_blank_template_rows_are_not_questions(self):
        text = (
            "```\n| 1 | Teaching | Example. | উদাহরণ | rating | yes | all |  |  |\n```\n"
            + HEADER
            + "| 1 |  |  |  |  |  |  |  |  |\n"
        )
        parsed = question_bank.parse(text)
        assert parsed.questions == []
        assert [item.reason for item in parsed.skipped] == ["Empty row."]

    @pytest.mark.parametrize(
        ("row", "reason"),
        [
            ("| 1 | Teaching | Only three | cells |", "Expected 9 columns, found 4."),
            ("| 1 | Teaching |  |  | rating | yes | all |  |  |", "No question text."),
            ("| 1 |  | Text | বাংলা | rating | yes | all |  |  |", "No category."),
            ("| 1 | Teaching | Text | বাংলা | essay | yes | all |  |  |", "Unknown type 'essay'."),
            (
                "| 1 | Teaching | Text | বাংলা | rating | maybe | all |  |  |",
                "Required must be yes or no.",
            ),
            (
                "| 1 | Teaching | Text | বাংলা | rating | yes | night |  |  |",
                "Unknown applies value 'night'.",
            ),
            (
                "| 1 | Teaching | Text | বাংলা | rating | yes | all | A / B |  |",
                "Only choice questions have options.",
            ),
            (
                "| 1 | Teaching | Text | বাংলা | choice | yes | all | Only |  |",
                "A choice question needs at least two options.",
            ),
            (
                "| 1 | Teaching | Text | বাংলা | choice | yes | all | A / B | ক |",
                "English and Bangla options differ in number.",
            ),
        ],
    )
    def test_malformed_rows_are_skipped_with_a_reason(self, row, reason):
        parsed = question_bank.parse(bank(row))
        assert parsed.questions == []
        assert [item.reason for item in parsed.skipped] == [reason]

    def test_a_bad_row_does_not_stop_the_good_ones(self):
        parsed = question_bank.parse(
            bank(
                "| 1 | Teaching | Good. | ভালো | rating |  |  |  |  |",
                "| 2 | Teaching | Bad. | খারাপ | essay | yes | all |  |  |",
            )
        )
        assert len(parsed.questions) == 1
        assert (parsed.questions[0].required, parsed.questions[0].applies_to) == (True, "all")
        assert [item.line for item in parsed.skipped] == [6]

    def test_rating_topics_become_categories_and_placeholders_are_ignored(self):
        text = (
            bank()
            + "\n## Rating topics (kon)\n- (pore likho)\n- Punctuality\n* Lab Support\n"
            + "\n## Other\n- Ignored\n"
        )
        assert question_bank.parse(text).topics == [("Punctuality", ""), ("Lab Support", "")]


ROW = "| 1 | Teaching | Real question. | আসল প্রশ্ন | rating | yes | all |  |  |"


class TestTopicsAndPlaceholders:
    def test_topic_lines_may_carry_a_bangla_name(self):
        topics = "- Punctuality / সময়ানুবর্তিতা\n- Lab / Theory Support\n- Odd /\n"
        parsed = question_bank.parse(bank() + "\n## Rating topics\n" + topics)
        assert parsed.topics == [
            ("Punctuality", "সময়ানুবর্তিতা"),
            ("Lab / Theory Support", ""),
            ("Odd /", ""),
        ]

    def test_both_names_are_stored_and_reloading_keeps_them(self):
        topics = "- Punctuality / সময়ানুবর্তিতা\n- Teaching / শিক্ষাদান\n"
        text = bank() + "\n## Rating topics\n" + topics
        QuestionCategory.objects.filter(name="Teaching").update(name_bn="পাঠদান")
        question_bank.load(text)
        question_bank.load(text)
        assert QuestionCategory.objects.get(name="Punctuality").name_bn == "সময়ানুবর্তিতা"
        assert QuestionCategory.objects.get(name="Teaching").name_bn == "পাঠদান"  # kept
        assert QuestionCategory.objects.filter(name="Punctuality").count() == 1

    def test_missing_bangla_name_falls_back_to_english(self):
        question_bank.load(bank() + "\n## Rating topics\n- Lab Support\n")
        assert QuestionCategory.objects.get(name="Lab Support").name_bn == ""

    def seeded(self):
        question_bank.load(bank())
        assert Question.objects.count() == 12

    def test_replace_placeholders_removes_unanswered_ones_when_real_questions_load(self):
        self.seeded()
        report = question_bank.load(bank(ROW), replace_placeholders=True)
        assert (report.placeholders_removed, report.placeholders_kept) == (12, 0)
        assert list(Question.objects.values_list("text", flat=True)) == ["Real question."]

    def test_answered_placeholders_stay(self):
        self.seeded()
        answered = Question.objects.get(text="Overall, how would you rate this course?")
        Answer.objects.create(
            response=FeedbackResponse.objects.create(**response_parts()),
            question=answered,
            int_value=4,
        )
        report = question_bank.load(bank(ROW), replace_placeholders=True)
        assert (report.placeholders_removed, report.placeholders_kept) == (11, 1)
        assert Question.objects.filter(pk=answered.pk).exists()

    def test_nothing_is_removed_without_the_flag_or_without_real_questions(self):
        self.seeded()
        question_bank.load(bank(ROW))
        assert Question.objects.count() == 13
        report = question_bank.load(bank(), replace_placeholders=True)
        assert report.placeholders_removed == 0
        assert Question.objects.count() == 13

    def test_a_real_row_with_a_placeholder_text_is_kept(self):
        self.seeded()
        text = "Overall, how would you rate this course?"
        row = f"| 1 | Overall | {text} | সামগ্রিক | rating | yes | all |  |  |"
        question_bank.load(bank(row), replace_placeholders=True)
        assert Question.objects.filter(text=text).count() == 1

    def test_command_reads_utf8_with_bom_and_replaces_placeholders(self, tmp_path, capsys):
        path = tmp_path / "bank.md"
        empty = tmp_path / "empty.md"
        empty.write_text(bank(), encoding="utf-8")
        call_command("load_questions", str(empty))
        path.write_bytes(b"\xef\xbb\xbf" + bank(ROW).encode("utf-8"))  # UTF-8 BOM
        call_command("load_questions", str(path), "--replace-placeholders")
        out = capsys.readouterr().out
        assert "Placeholders: 12 removed, 0 kept" in out
        assert Question.objects.get().text_bn == "আসল প্রশ্ন"


class TestLoad:
    ROWS = (
        "| 1 | Teaching | The teacher is clear. | শিক্ষক স্পষ্ট। | rating | yes | all |  |  |",
        "| 2 | New Topic | Lab kit was enough. | ল্যাবের সরঞ্জাম যথেষ্ট ছিল। "
        "| choice | no | lab | Yes / Partly / No | হ্যাঁ / আংশিক / না |",
    )

    def test_creates_questions_and_categories(self):
        report = question_bank.load(bank(*self.ROWS) + "\n## Rating topics\n- Punctuality\n")
        assert (report.created, report.updated, report.categories) == (2, 0, 2)
        lab = Question.objects.get(text="Lab kit was enough.")
        assert lab.category.name == "New Topic"
        assert lab.options[0] == {"value": "yes", "en": "Yes", "bn": "হ্যাঁ"}
        assert (lab.required, lab.applies_to, lab.order) == (False, "lab", 20)
        assert QuestionCategory.objects.filter(name="Punctuality").exists()

    def test_loading_twice_changes_nothing(self):
        text = bank(*self.ROWS)
        question_bank.load(text)
        before = list(Question.objects.values())
        events = AuditEvent.objects.count()
        report = question_bank.load(text)
        assert (report.created, report.updated, report.unchanged) == (0, 0, 2)
        assert list(Question.objects.values()) == before
        assert AuditEvent.objects.filter(action__startswith="feedback.question_").count() == 2
        assert AuditEvent.objects.count() == events + 1  # only the load itself

    def test_changed_row_updates_in_place_without_answers(self):
        question_bank.load(bank(self.ROWS[0]))
        report = question_bank.load(bank(self.ROWS[0].replace("| yes |", "| no |")))
        assert (report.updated, Question.objects.count()) == (1, 1)
        assert Question.objects.get().required is False

    def test_changed_wording_of_an_answered_question_becomes_a_new_version(self):
        question_bank.load(bank(self.ROWS[0]))
        old = Question.objects.get()
        Answer.objects.create(
            response=FeedbackResponse.objects.create(**response_parts()), question=old, int_value=3
        )
        report = question_bank.load(bank(self.ROWS[0].replace("rating", "likert")))
        new = Question.objects.get(is_active=True)
        assert report.updated == 1
        assert (new.version, new.supersedes_id, new.question_type) == (2, old.pk, "likert")
        old.refresh_from_db()
        assert old.is_active is False and old.question_type == "rating"

    def test_skipped_rows_are_reported_and_the_rest_loaded(self):
        report = question_bank.load(
            bank(self.ROWS[0], "| 3 | Teaching | Bad. | x | essay | yes | all |  |  |")
        )
        assert (report.created, [item.reason for item in report.skipped]) == (
            1,
            ["Unknown type 'essay'."],
        )

    def test_placeholders_only_when_table_and_bank_are_empty(self):
        empty = bank("| 1 |  |  |  |  |  |  |  |  |")
        report = question_bank.load(empty)
        assert report.placeholders == 12
        assert Question.objects.count() == 12
        assert question_bank.load(empty).placeholders == 0
        assert Question.objects.count() == 12

    def test_placeholders_do_not_join_a_bank_that_has_questions(self):
        make_question(QuestionType.RATING)
        assert question_bank.load(bank()).placeholders == 0
        assert Question.objects.count() == 1

    def test_command_reads_the_file_and_reports_skips(self, tmp_path, capsys):
        path = tmp_path / "bank.md"
        path.write_text(
            bank(self.ROWS[0], "| 2 | Teaching | Bad. | x | essay | yes | all |  |  |"),
            encoding="utf-8",
        )
        call_command("load_questions", str(path))
        captured = capsys.readouterr()
        assert "1 created" in captured.out
        assert "Skipped line 6: Unknown type 'essay'." in captured.err


def response_parts():
    offering = make_offering()
    return {"offering": offering, "window": make_window(offering.semester)}


class TestVersioning:
    DATA = {
        "category": None,
        "text": "Clear?",
        "text_bn": "",
        "question_type": "rating",
        "options": [],
        "required": True,
        "applies_to": "all",
    }

    def data(self, **changes):
        return {**self.DATA, **changes}

    def test_unanswered_question_is_edited_in_place(self, admin):
        question = questions.create_question(self.data(), actor=admin)
        saved = questions.update_question(question.pk, self.data(text="Very clear?"), actor=admin)
        assert (saved.pk, saved.text, saved.version) == (question.pk, "Very clear?", 1)
        assert "feedback.question_updated" in actions()

    def test_answered_question_gets_a_new_version_and_the_old_one_is_deactivated(self, admin):
        question = questions.create_question(self.data(), actor=admin)
        Answer.objects.create(
            response=FeedbackResponse.objects.create(**response_parts()),
            question=question,
            int_value=4,
        )
        saved = questions.update_question(question.pk, self.data(text="Very clear?"), actor=admin)
        question.refresh_from_db()
        assert saved.pk != question.pk
        assert (saved.version, saved.supersedes_id, saved.order) == (2, question.pk, question.order)
        assert (question.text, question.is_active) == ("Clear?", False)
        assert "feedback.question_versioned" in actions()

    def test_answered_question_still_allows_non_wording_changes_in_place(self, admin):
        question = questions.create_question(self.data(), actor=admin)
        Answer.objects.create(
            response=FeedbackResponse.objects.create(**response_parts()),
            question=question,
            int_value=4,
        )
        saved = questions.update_question(
            question.pk, self.data(required=False, applies_to="lab"), actor=admin
        )
        assert (saved.pk, saved.version, saved.required, saved.applies_to) == (
            question.pk,
            1,
            False,
            "lab",
        )

    def test_a_superseded_version_cannot_be_edited_or_reactivated(self, admin):
        question = questions.create_question(self.data(), actor=admin)
        Answer.objects.create(
            response=FeedbackResponse.objects.create(**response_parts()),
            question=question,
            int_value=4,
        )
        questions.update_question(question.pk, self.data(text="Changed"), actor=admin)
        with pytest.raises(ValidationError):
            questions.update_question(question.pk, self.data(text="Again"), actor=admin)
        with pytest.raises(ValidationError):
            questions.set_active(question.pk, True, actor=admin)

    def test_option_values_survive_an_edit(self):
        before = questions.build_options(["Yes", "Partly"], ["হ্যাঁ", "আংশিক"])
        after = questions.build_options(["Partly", "No", "Yes"], [], before)
        assert {option["en"]: option["value"] for option in after} == {
            "Partly": "partly",
            "No": "no",
            "Yes": "yes",
        }

    def test_duplicate_is_an_inactive_fresh_copy(self, admin):
        question = questions.create_question(self.data(), actor=admin)
        copy = questions.duplicate_question(question.pk, actor=admin)
        assert (copy.is_active, copy.version, copy.supersedes_id, copy.text) == (
            False,
            1,
            None,
            "Clear?",
        )
        assert copy.order > question.order
        assert "feedback.question_duplicated" in actions()

    def test_reorder_renumbers_and_is_audited(self, admin):
        first, second, third = (make_question(QuestionType.TEXT) for _ in range(3))
        questions.reorder({first.pk: 3, second.pk: 1, third.pk: 2}, actor=admin)
        ordered = list(Question.objects.order_by("order").values_list("pk", flat=True))
        assert ordered == [second.pk, third.pk, first.pk]
        assert "feedback.questions_reordered" in actions()


class TestQuestionScreens:
    @pytest.fixture
    def client_admin(self, client, admin):
        client.defaults["HTTP_ACCEPT_LANGUAGE"] = "en"
        sign_in(client, admin)
        return client

    def form(self, **changes):
        return {
            "category": QuestionCategory.objects.get(name="Teaching").pk,
            "text": "Is it clear?",
            "text_bn": "স্পষ্ট?",
            "question_type": "choice",
            "options_en": "Yes\nPartly\nNo",
            "options_bn": "হ্যাঁ\nআংশিক\nনা",
            "required": "on",
            "applies_to": "all",
            **changes,
        }

    def test_create_edit_toggle_duplicate_and_reorder(self, client_admin):
        response = client_admin.post(reverse("feedback:question_create"), self.form())
        assert response.status_code == 302
        question = Question.objects.get()
        assert [option["value"] for option in question.options] == ["yes", "partly", "no"]
        client_admin.post(reverse("feedback:question_toggle", args=[question.pk]))
        question.refresh_from_db()
        assert question.is_active is False
        client_admin.post(reverse("feedback:question_duplicate", args=[question.pk]))
        assert Question.objects.count() == 2
        client_admin.post(
            reverse("feedback:question_reorder"), {f"order_{question.pk}": "9", "order_x": "1"}
        )
        assert (
            reverse("feedback:questions")
            in client_admin.get(reverse("feedback:questions")).request["PATH_INFO"]
        )
        assert {"feedback.question_created", "feedback.question_deactivated"} <= actions()

    def test_a_choice_question_needs_options(self, client_admin):
        response = client_admin.post(
            reverse("feedback:question_create"), self.form(options_en="Only")
        )
        assert response.status_code == 200
        assert Question.objects.count() == 0

    def test_editing_an_answered_question_reports_the_new_version(self, client_admin):
        question = questions.create_question(
            {
                "category": None,
                "text": "Old",
                "text_bn": "",
                "question_type": "text",
                "options": [],
                "required": True,
                "applies_to": "all",
            },
            actor=None,
        )
        Answer.objects.create(
            response=FeedbackResponse.objects.create(**response_parts()),
            question=question,
            encrypted_text="hi",
        )
        page = client_admin.get(reverse("feedback:question_edit", args=[question.pk]))
        assert "saves a new version" in page.content.decode()
        client_admin.post(
            reverse("feedback:question_edit", args=[question.pk]),
            self.form(question_type="text", options_en="", options_bn="", text="New"),
        )
        assert Question.objects.get(is_active=True).text == "New"

    def test_categories_can_be_added_and_renamed(self, client_admin):
        client_admin.post(
            reverse("feedback:categories"), {"name": "Facilities", "name_bn": "", "order": 70}
        )
        category = QuestionCategory.objects.get(name="Facilities")
        client_admin.post(
            reverse("feedback:category_edit", args=[category.pk]),
            {"name": "Facility", "name_bn": "", "order": 70},
        )
        category.refresh_from_db()
        assert category.name == "Facility"
        assert {"feedback.category_created", "feedback.category_updated"} <= actions()

    @pytest.mark.parametrize(
        "name",
        [
            "questions",
            "question_create",
            "categories",
            "windows",
            "window_create",
            "question_reorder",
        ],
    )
    def test_screens_are_admin_only(self, client, name):
        assert client.get(reverse(f"feedback:{name}")).status_code == 302
        student = enrolled_student(make_offering())
        sign_in(client, student.registry.claimed_by)
        assert client.get(reverse(f"feedback:{name}")).status_code == 403


class TestSubmitRespectsRequired:
    def test_optional_blank_stores_nothing_and_required_blank_is_an_error(self):
        required = make_question(QuestionType.RATING, required=True)
        optional = make_question(QuestionType.RATING, required=False)
        rows = clean_answers(Question.objects.all(), {required.pk: "4", optional.pk: ""})
        assert [row["question"] for row in rows] == [required]
        with pytest.raises(ValidationError) as caught:
            clean_answers(Question.objects.all(), {required.pk: "", optional.pk: "2"})
        assert list(caught.value.error_dict) == [required.pk]

    def test_an_admin_made_optional_question_can_be_skipped(self, admin):
        question = questions.create_question(
            {
                "category": None,
                "text": "Optional",
                "text_bn": "",
                "question_type": "rating",
                "options": [],
                "required": True,
                "applies_to": "all",
            },
            actor=admin,
        )
        with pytest.raises(ValidationError):
            clean_answers(Question.objects.all(), {})
        questions.update_question(
            question.pk,
            {
                "category": None,
                "text": "Optional",
                "text_bn": "",
                "question_type": "rating",
                "options": [],
                "required": False,
                "applies_to": "all",
            },
            actor=admin,
        )
        assert clean_answers(Question.objects.all(), {}) == []


class TestWindowStatus:
    def test_status_at_the_boundary_instants(self):
        window = FeedbackWindow(opens_at=at(9), closes_at=at(17))
        one = timedelta(seconds=1)
        expected = [
            (at(9) - one, WindowStatus.UPCOMING),
            (at(9), WindowStatus.OPEN),
            (at(17) - one, WindowStatus.OPEN),
            (at(17), WindowStatus.CLOSED),
            (at(17) + one, WindowStatus.CLOSED),
        ]
        assert [window.status(now) for now, _ in expected] == [status for _, status in expected]

    def test_inactive_window_is_never_open_but_keeps_its_status(self):
        window = FeedbackWindow(opens_at=at(9), closes_at=at(17), is_active=False)
        assert window.status(at(12)) == WindowStatus.OPEN
        assert not window.is_open(at(12))

    def test_server_accepts_the_last_open_instant_and_rejects_the_closing_instant(
        self, monkeypatch
    ):
        offering = make_offering()
        student = enrolled_student(offering)
        window = FeedbackWindow.objects.create(
            semester=offering.semester, name="R", opens_at=at(9), closes_at=at(17)
        )

        def check(now):
            monkeypatch.setattr(eligibility.timezone, "now", lambda: now)
            return eligibility.check_eligible(student, offering, window)

        assert check(at(17) - timedelta(microseconds=1))
        with pytest.raises(SubmissionRejected) as caught:
            check(at(17))
        assert caught.value.reason == Rejection.WINDOW_CLOSED
        with pytest.raises(SubmissionRejected):
            check(at(9) - timedelta(microseconds=1))


class TestWindowOverlap:
    @pytest.fixture
    def semester(self):
        return make_semester()

    def make(self, semester, opens, closes, **fields):
        departments = fields.pop("departments", ())
        level_terms = fields.pop("level_terms", ())
        window = FeedbackWindow.objects.create(
            semester=semester,
            name=fields.pop("name", f"W{FeedbackWindow.objects.count()}"),
            opens_at=at(*opens),
            closes_at=at(*closes),
            **fields,
        )
        window.departments.set(departments)
        window.level_terms.set(level_terms)
        return window

    def clashes(self, semester, opens, closes, departments=(), level_terms=(), **kwargs):
        return windows.find_overlapping(
            semester,
            at(*opens),
            at(*closes),
            {d.pk for d in departments},
            {t.pk for t in level_terms},
            **kwargs,
        )

    def test_same_scope_and_time_overlap(self, semester):
        existing = self.make(semester, (9,), (17,))
        assert self.clashes(semester, (16,), (20,)) == [existing]
        assert self.clashes(semester, (10,), (12,)) == [existing]

    def test_touching_rounds_do_not_overlap(self, semester):
        self.make(semester, (9,), (17,))
        assert self.clashes(semester, (17,), (20,)) == []
        assert self.clashes(semester, (6,), (9,)) == []

    def test_other_semester_inactive_and_self_are_ignored(self, semester):
        self.make(semester, (9,), (17,), is_active=False)
        assert self.clashes(semester, (10,), (12,)) == []
        other = self.make(semester, (9,), (17,))
        assert self.clashes(semester, (10,), (12,), exclude_pk=other.pk) == []
        assert self.clashes(make_semester(), (10,), (12,)) == []

    def test_scopes_must_intersect_in_both_dimensions(self, semester):
        cse, eee = DepartmentFactory(), DepartmentFactory()
        first, second = LevelTermFactory(), LevelTermFactory()
        existing = self.make(semester, (9,), (17,), departments=[cse], level_terms=[first])
        assert self.clashes(semester, (10,), (12,), [eee], [first]) == []
        assert self.clashes(semester, (10,), (12,), [cse], [second]) == []
        assert self.clashes(semester, (10,), (12,), [cse], [first]) == [existing]
        assert self.clashes(semester, (10,), (12,), [cse]) == [existing]  # unrestricted levels
        assert self.clashes(semester, (10,), (12,)) == [existing]  # unrestricted everything

    def form_data(self, semester, **changes):
        local = timezone.get_current_timezone()
        return {
            "semester": semester.pk,
            "name": "Round X",
            "opens_at": datetime(2030, 3, 1, 15, 0, tzinfo=local).strftime("%Y-%m-%dT%H:%M"),
            "closes_at": datetime(2030, 3, 1, 23, 0, tzinfo=local).strftime("%Y-%m-%dT%H:%M"),
            "is_active": "on",
            **changes,
        }

    def test_form_rejects_an_overlapping_round_and_accepts_a_clear_one(self, semester):
        self.make(semester, (9,), (17,))  # UTC; the form below is in Asia/Dhaka (UTC+6)
        clash = WindowForm(self.form_data(semester))
        assert not clash.is_valid()
        assert "overlaps" in clash.non_field_errors()[0]
        later = WindowForm(
            self.form_data(semester, opens_at="2030-03-02T09:00", closes_at="2030-03-02T12:00")
        )
        assert later.is_valid(), later.errors

    def test_form_requires_closing_after_opening(self, semester):
        form = WindowForm(self.form_data(semester, closes_at="2030-03-01T15:00"))
        assert not form.is_valid()
        assert "closes_at" in form.errors

    def test_inactive_round_may_overlap_but_reactivating_is_checked(self, semester):
        self.make(semester, (9,), (17,))
        draft = WindowForm(self.form_data(semester).copy() | {"is_active": ""})
        assert draft.is_valid()
        saved = windows.save_window(draft, actor=make_admin())
        again = WindowForm(self.form_data(semester), instance=saved)
        assert not again.is_valid()

    def test_save_rechecks_under_the_lock(self, semester):
        form = WindowForm(self.form_data(semester))
        assert form.is_valid()
        self.make(semester, (9,), (17,))  # lands between validation and save
        with pytest.raises(ValidationError):
            windows.save_window(form, actor=make_admin())
        assert FeedbackWindow.objects.count() == 1

    def test_closed_round_times_and_scope_are_locked(self, semester):
        past = FeedbackWindow.objects.create(
            semester=semester,
            name="Past",
            opens_at=timezone.now() - timedelta(days=3),
            closes_at=timezone.now() - timedelta(days=2),
        )
        form = WindowForm(
            {
                "semester": semester.pk,
                "name": "Renamed",
                "opens_at": "2030-01-01T09:00",
                "closes_at": "2030-01-02T09:00",
                "is_active": "on",
            },
            instance=past,
        )
        assert form.is_valid(), form.errors
        saved = windows.save_window(form, actor=make_admin())
        assert saved.name == "Renamed"
        assert saved.closes_at < timezone.now()


class TestWindowScreens:
    @pytest.fixture
    def client_admin(self, client, admin):
        client.defaults["HTTP_ACCEPT_LANGUAGE"] = "en"
        sign_in(client, admin)
        return client

    def test_create_list_and_preview(self, client_admin):
        semester = make_semester(current=True)
        offering = make_offering(make_course(course_type=CourseType.LAB), semester)
        make_question(QuestionType.RATING, text="Lab question", applies_to=AppliesTo.LAB)
        make_question(QuestionType.RATING, text="Theory question", applies_to=AppliesTo.THEORY)
        response = client_admin.post(
            reverse("feedback:window_create"),
            {
                "semester": semester.pk,
                "name": "Mid",
                "opens_at": "2030-01-01T09:00",
                "closes_at": "2030-01-05T09:00",
                "is_active": "on",
                "departments": [offering.course.department_id],
            },
        )
        assert response.status_code == 302
        window = FeedbackWindow.objects.get()
        assert window.opens_at == datetime(2030, 1, 1, 3, 0, tzinfo=UTC)  # 09:00 in Dhaka
        listing = client_admin.get(reverse("feedback:windows")).content.decode()
        assert "Upcoming" in listing and "Mid" in listing
        preview = client_admin.get(
            reverse("feedback:window_preview", args=[window.pk])
        ).content.decode()
        assert "1 course offering is covered" in preview
        assert "Lab question" in preview and "Theory question" in preview
        assert "feedback.window_created" in actions()

    def test_overlap_is_a_form_error_not_a_second_round(self, client_admin):
        semester = make_semester()
        data = {
            "semester": semester.pk,
            "name": "A",
            "opens_at": "2030-01-01T09:00",
            "closes_at": "2030-01-05T09:00",
            "is_active": "on",
        }
        client_admin.post(reverse("feedback:window_create"), data)
        response = client_admin.post(reverse("feedback:window_create"), data | {"name": "B"})
        assert response.status_code == 200
        assert FeedbackWindow.objects.count() == 1


def test_question_pages_name_categories_in_the_active_language(client, admin):
    category = QuestionCategory.objects.create(name="Punctuality", name_bn="সময়ানুবর্তিতা")
    question = make_question(QuestionType.RATING, category=category)
    sign_in(client, admin)
    client.defaults["HTTP_ACCEPT_LANGUAGE"] = "bn"

    listing = client.get(reverse("feedback:questions")).content.decode()
    form = client.get(reverse("feedback:question_edit", args=[question.pk])).content.decode()

    assert ">সময়ানুবর্তিতা<" in listing and ">Punctuality<" not in listing
    assert ">সময়ানুবর্তিতা</option>" in form
    with translation.override("en"):
        assert str(category) == "Punctuality"
