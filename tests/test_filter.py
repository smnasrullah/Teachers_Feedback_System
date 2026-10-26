import json
import urllib.error
from http.client import HTTPException

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import translation

from apps.academics.models import CourseType
from apps.auditlog.models import AuditEvent
from apps.feedback.models import Answer, FilterTerm, FilterTermKind, QuestionType
from apps.feedback.services import filter as text_filter
from apps.feedback.services import filter_terms, moderation, wordlist
from apps.feedback.services.filter import Reason, clean, preview_clean
from apps.feedback.services.moderation import AnthropicBackend, NullBackend
from apps.feedback.services.submit import submit_feedback
from tests.factories import DepartmentFactory, make_admin, sign_in
from tests.test_academics import make_course, make_offering, make_semester
from tests.test_feedback_core import enrolled_student, make_question, make_window

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _english():
    with translation.override("en"):
        yield


class TestAbuse:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            (
                "He is a fucking teacher and the class was good.",
                "He is a teacher and the class was good.",
            ),
            ("What a bitch.", "What a."),
            ("Sir is a bastard, but explains well", "Sir is a, but explains well"),
            ("তুমি একটা হারামজাদা শিক্ষক, পড়ানো ভালো", "তুমি একটা শিক্ষক, পড়ানো ভালো"),
            ("স্যার কুত্তার মতো আচরণ করেন", "স্যার মতো আচরণ করেন"),
            ("sir is a madarchod but good", "sir is a but good"),
            ("Tumi ekta kutta, class valo", "Tumi ekta, class valo"),
        ],
    )
    def test_abusive_words_in_english_bangla_and_banglish_are_removed(self, text, expected):
        result = clean(text)
        assert result.text == expected
        assert result.flagged
        assert result.removed_count == 1
        assert result.reasons == (Reason.PROFANITY,)

    @pytest.mark.parametrize(
        "text",
        [
            "FUCK this",
            "fuuuuuuck this",
            "fuuck this",
            "f*ck this",
            "f**k this",
            "fu​ck this",
            "ｆｕｃｋ this",  # noqa: RUF001
            "sh!t this",
            "a$$hole this",
            "a$$ this",
            "5h1t this",
            "fucking this",
            "sh1tty this",
            "bokachooooda this",
        ],
    )
    def test_disguised_abuse_is_found(self, text):
        result = clean(text)
        assert result.text == "this"
        assert result.flagged

    def test_punctuation_around_a_word_is_kept(self):
        assert clean("What the shit!!! Really.").text == "What the!!! Really."

    @pytest.mark.parametrize(
        "text",
        [
            "Hello, the class assessment was a classic. Scunthorpe, Dickens and Cockburn too.",
            "The assistant passed the bassoon to the assassin in Essex, a masterpiece.",
            "I can't say the game was bad: a ball, a hall, all fine.",
            "বালক বালিকা বালিশ বালু এবং ভালো পড়ানো",
            "Great teacher! 10/10, would recommend :)",
        ],
    )
    def test_innocent_words_containing_a_blocked_word_are_not_flagged(self, text):
        result = clean(text)
        assert result.text == text
        assert not result.flagged
        assert result.removed_count == 0

    def test_clean_text_is_unchanged_byte_for_byte(self):
        text = "Clear lectures,  more examples please.\nThanks — বাংলায়ও ভালো!"
        assert clean(text).text == text

    def test_mask_action_stars_the_word_out(self, settings):
        settings.PROFANITY_ACTION = "mask"
        result = clean("you idiot sir")
        assert result.text == "you ***** sir"
        assert result.flagged

    def test_allow_list_wins_over_the_blocked_list(self):
        assert clean("Dick Van Dyke").text == "Van Dyke"
        filter_terms.add_term("dick", FilterTermKind.ALLOW, actor=None)
        assert clean("Dick Van Dyke").text == "Dick Van Dyke"

    def test_admin_added_words_are_blocked(self):
        filter_terms.add_term("grumpkin", FilterTermKind.BLOCK, actor=None)
        assert clean("a grumpkin teacher").text == "a teacher"

    def test_word_files_ignore_comments_and_blank_lines(self):
        assert wordlist.parse_list("# note\n\nFoo\n  # x\nBAR \n") == {"foo", "bar"}


class TestPersonalDetails:
    @pytest.mark.parametrize(
        "phone",
        [
            "01712345678",
            "+8801712345678",
            "+880 1712-345678",
            "017 1234 5678",
            "০১৭১২৩৪৫৬৭৮",
            "8801912345678",
        ],
    )
    def test_bangladeshi_phone_numbers_are_removed(self, phone):
        result = clean(f"Call me on {phone} for details")
        assert result.text == "Call me on for details"
        assert result.reasons == (Reason.PERSONAL_INFO,)
        assert not result.flagged

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("mail rahim.k@example.com now", "mail now"),
            ("see https://facebook.com/rahim.k now", "see now"),
            ("see www.example.org/page now", "see now"),
            ("see rahim.edu now", "see now"),
            ("my id 180104076 now", "my id now"),
            ("my id 2021-1-60-123 now", "my id now"),
            ("my id ১৮০১০৪০৭৬ now", "my id now"),
        ],
    )
    def test_emails_links_and_ids_are_removed(self, text, expected):
        result = clean(text)
        assert result.text == expected
        assert result.removed_count == 1

    def test_short_numbers_and_dates_stay(self):
        text = "In 2024 I scored 85/100 in 12-05-2024 for 3 credits"
        assert clean(text).text == text

    def test_a_comment_with_only_personal_details_is_empty(self):
        result = clean("01712345678")
        assert result.empty
        assert result.reasons == (Reason.PERSONAL_INFO,)


class TestJunk:
    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            "...",
            "!!!???",
            "12345",
            "10/10",
            "😀😀😀",
            "asdfghjkl",
            "qwerty",
            "lkjhgf",
            "aaaaaaaa",
            "hahahahaha",
            "xzcvbnm",
            "asdf asdf",
            "bcdfghjklmnp",
            "zxcv",
        ],
    )
    def test_nothing_meaningful_is_empty(self, text):
        result = clean(text)
        assert result.empty
        assert result.reasons

    def test_empty_input_says_empty_and_gibberish_says_gibberish(self):
        assert clean("  ").reasons == (Reason.EMPTY,)
        assert clean("asdfghjkl").reasons == (Reason.GIBBERISH,)

    @pytest.mark.parametrize("text", ["ok", "No", "Good", "N/A", "প", "A+", "Sir is very nice"])
    def test_short_real_answers_survive(self, text):
        assert clean(text).text == text

    def test_a_removed_word_can_leave_nothing(self):
        result = clean("fuck!!!")
        assert result.empty
        assert result.flagged
        assert result.reasons == (Reason.PROFANITY,)

    def test_reasons_are_readable_in_the_active_language(self):
        assert clean("fuck").messages() == ["Abusive words are not allowed."]
        with translation.override("bn"):
            assert clean("fuck").messages() != ["Abusive words are not allowed."]

    def test_preview_never_calls_the_ai_backend(self, monkeypatch):
        def boom():
            raise AssertionError("AI backend used")

        monkeypatch.setattr(text_filter, "get_backend", boom)
        assert preview_clean("fine comment").text == "fine comment"


class FakeBackend:
    def __init__(self, terms):
        self.terms = terms
        self.seen = []

    def abusive_terms(self, text):
        self.seen.append(text)
        return self.terms


class TestAiBackend:
    def test_null_backend_is_the_default(self):
        assert isinstance(moderation.get_backend(), NullBackend)

    def test_enabled_without_a_key_stays_off(self, settings):
        settings.FILTER_AI_ENABLED = True
        settings.ANTHROPIC_API_KEY = ""
        assert isinstance(moderation.get_backend(), NullBackend)

    def test_enabled_with_a_key_uses_anthropic(self, settings):
        settings.FILTER_AI_ENABLED = True
        settings.ANTHROPIC_API_KEY = "key"
        assert isinstance(moderation.get_backend(), AnthropicBackend)

    def test_terms_found_by_the_backend_are_removed_and_flagged(self, monkeypatch):
        backend = FakeBackend(("lazy sloth", "invented"))
        monkeypatch.setattr(text_filter, "get_backend", lambda: backend)
        result = clean("Sir is a lazy sloth, 01712345678 and the lectures slothful")
        assert result.text == "Sir is a, and the lectures slothful"
        assert result.flagged
        assert result.removed_count == 2
        # Only the text reaches the backend, with personal details already gone.
        assert backend.seen == ["Sir is a lazy sloth,  and the lectures slothful"]

    def test_the_backend_is_skipped_when_nothing_is_left(self, monkeypatch):
        backend = FakeBackend(())
        monkeypatch.setattr(text_filter, "get_backend", lambda: backend)
        assert clean("fuck").empty
        assert backend.seen == []

    @pytest.fixture
    def anthropic(self):
        return AnthropicBackend("secret-key", "claude-haiku-5-5", 3.0)

    @staticmethod
    def reply(text):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, limit):
                return json.dumps({"content": [{"type": "text", "text": text}]}).encode()

        return Response()

    def test_anthropic_request_carries_only_the_comment(self, anthropic, monkeypatch):
        sent = {}

        def fake_urlopen(request, timeout):
            sent.update(request=request, timeout=timeout)
            return self.reply('["jerk", 7, "", "x"]')

        monkeypatch.setattr(moderation.urllib.request, "urlopen", fake_urlopen)
        assert anthropic.abusive_terms("what a jerk") == ("jerk", "x")
        request = sent["request"]
        body = json.loads(request.data)
        assert body["messages"] == [{"role": "user", "content": "what a jerk"}]
        assert request.get_header("X-api-key") == "secret-key"
        assert sent["timeout"] == 3.0

    @pytest.mark.parametrize(
        "failure",
        [
            TimeoutError("timed out"),
            urllib.error.URLError("down"),
            HTTPException("bad"),
            ConnectionResetError(),
        ],
    )
    def test_network_failures_fail_open(self, anthropic, monkeypatch, failure):
        def fail(request, timeout):
            raise failure

        monkeypatch.setattr(moderation.urllib.request, "urlopen", fail)
        assert anthropic.abusive_terms("what a jerk") == ()

    @pytest.mark.parametrize("text", ["not json", '{"a": 1}', "[1, 2]", ""])
    def test_unusable_replies_fail_open(self, anthropic, monkeypatch, text):
        monkeypatch.setattr(
            moderation.urllib.request, "urlopen", lambda request, timeout: self.reply(text)
        )
        assert anthropic.abusive_terms("what a jerk") == ()

    def test_a_timeout_leaves_the_local_layers_in_charge(self, settings, monkeypatch):
        settings.FILTER_AI_ENABLED = True
        settings.ANTHROPIC_API_KEY = "key"

        def fail(request, timeout):
            raise TimeoutError

        monkeypatch.setattr(moderation.urllib.request, "urlopen", fail)
        result = clean("fuck this and 01712345678 that")
        assert result.text == "this and that"
        assert result.flagged

    def test_failures_never_log_the_comment(self, anthropic, monkeypatch, caplog):
        def fail(request, timeout):
            raise TimeoutError("secret comment text")

        monkeypatch.setattr(moderation.urllib.request, "urlopen", fail)
        anthropic.abusive_terms("secret comment text")
        assert "secret comment text" not in caplog.text


@pytest.fixture
def form():
    department = DepartmentFactory()
    semester = make_semester(current=True)
    offering = make_offering(make_course(department, course_type=CourseType.THEORY), semester)
    return {
        "offering": offering,
        "window": make_window(semester),
        "student": enrolled_student(offering),
        "required": make_question(QuestionType.TEXT, order=1),
        "optional": make_question(QuestionType.TEXT, order=2, required=False),
    }


def submit(form, **texts):
    answers = {form[name].pk: text for name, text in texts.items()}
    return submit_feedback(
        form["student"], form["offering"], form["window"], answers, reauth_ok=True
    )


def messages_for(excinfo, question):
    return [m for error in excinfo.value.error_dict[question.pk] for m in error.messages]


class TestSubmitting:
    def test_abusive_words_are_removed_before_storing_and_the_answer_is_flagged(self, form):
        submit(form, required="Good but he is an idiot", optional="Fine")
        stored = {a.question_id: a for a in Answer.objects.all()}
        assert stored[form["required"].pk].encrypted_text == "Good but he is an"
        assert stored[form["required"].pk].flagged
        assert stored[form["optional"].pk].encrypted_text == "Fine"
        assert not stored[form["optional"].pk].flagged

    def test_optional_text_left_empty_is_dropped_but_the_rest_is_kept(self, form):
        submit(form, required="Good", optional="fuck 01712345678")
        assert list(Answer.objects.values_list("question_id", flat=True)) == [form["required"].pk]

    def test_required_text_left_empty_asks_for_a_rewrite_with_the_reasons(self, form):
        with pytest.raises(ValidationError) as excinfo:
            submit(form, required="idiot!!!", optional="")
        errors = messages_for(excinfo, form["required"])
        assert "rewrite" in errors[0]
        assert "Abusive words are not allowed." in errors[0]
        assert not Answer.objects.exists()

    def test_gibberish_in_required_text_is_refused(self, form):
        with pytest.raises(ValidationError) as excinfo:
            submit(form, required="asdfghjkl")
        assert "random characters" in messages_for(excinfo, form["required"])[0]

    def test_the_audit_trail_holds_no_comment_text(self, form):
        submit(form, required="Good but he is an idiot")
        assert "idiot" not in json.dumps(
            list(AuditEvent.objects.values_list("metadata", flat=True))
        )


class TestAdminScreens:
    @pytest.fixture
    def admin_client(self, client):
        client.defaults["HTTP_ACCEPT_LANGUAGE"] = "en"
        sign_in(client, make_admin())
        return client

    def test_words_can_be_added_listed_and_removed(self, admin_client):
        url = reverse("feedback:filter_terms")
        admin_client.post(url, {"term": "  GRUMPKIN ", "kind": "block"})
        admin_client.post(url, {"term": "dick", "kind": "allow"})
        assert set(FilterTerm.objects.values_list("term", "kind")) == {
            ("grumpkin", "block"),
            ("dick", "allow"),
        }
        page = admin_client.get(url).content.decode()
        assert "grumpkin" in page
        assert "Allowed words" in page
        term = FilterTerm.objects.get(term="grumpkin")
        admin_client.post(reverse("feedback:filter_term_delete", args=[term.pk]))
        assert not FilterTerm.objects.filter(term="grumpkin").exists()
        assert {"feedback.filter_term_added", "feedback.filter_term_removed"} <= set(
            AuditEvent.objects.values_list("action", flat=True)
        )

    @pytest.mark.parametrize("term", ["two words", "", "x" * 65])
    def test_only_a_single_word_is_accepted(self, admin_client, term):
        admin_client.post(reverse("feedback:filter_terms"), {"term": term, "kind": "block"})
        assert not FilterTerm.objects.exists()

    def test_a_duplicate_word_is_refused(self, admin_client):
        url = reverse("feedback:filter_terms")
        admin_client.post(url, {"term": "grumpkin", "kind": "block"})
        response = admin_client.post(url, {"term": "Grumpkin", "kind": "block"})
        assert "already in the list" in response.content.decode()
        assert FilterTerm.objects.count() == 1

    def test_a_word_added_in_the_admin_applies_at_once(self, admin_client):
        assert clean("a grumpkin teacher").text == "a grumpkin teacher"
        admin_client.post(reverse("feedback:filter_terms"), {"term": "grumpkin", "kind": "block"})
        assert clean("a grumpkin teacher").text == "a teacher"
        FilterTerm.objects.get(term="grumpkin")
        admin_client.post(
            reverse(
                "feedback:filter_term_delete", args=[FilterTerm.objects.get(term="grumpkin").pk]
            )
        )
        assert clean("a grumpkin teacher").text == "a grumpkin teacher"

    def test_flagged_comments_show_cleaned_text_only(self, admin_client, form):
        submit(form, required="Good but he is an idiot", optional="Fine")
        page = admin_client.get(reverse("feedback:moderation")).content.decode()
        assert "Good but he is an" in page
        assert "idiot" not in page
        assert "Fine" not in page
        assert form["offering"].course.title not in page

    def test_only_the_admin_may_open_the_screens(self, client):
        for name in ("feedback:filter_terms", "feedback:moderation"):
            assert client.get(reverse(name)).status_code in (302, 403, 404)
        sign_in(client, make_admin())
        assert client.get(reverse("feedback:moderation")).status_code == 200


def test_normalise_term_rejects_anything_but_one_word():
    assert filter_terms.normalise_term(" Foo ") == "foo"
    with pytest.raises(ValidationError):
        filter_terms.normalise_term("foo bar")
