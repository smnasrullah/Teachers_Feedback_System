"""Admin forms for the question bank and feedback rounds."""

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledFormMixin
from apps.feedback.models import (
    AppliesTo,
    FeedbackWindow,
    Question,
    QuestionCategory,
    QuestionType,
    WindowStatus,
)
from apps.feedback.services import questions, windows

DATETIME_FORMAT = "%Y-%m-%dT%H:%M"
DATETIME_INPUT = forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DATETIME_FORMAT)


def _lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


class QuestionForm(StyledFormMixin, forms.ModelForm):
    """Options are typed one per line (English and Bangla in step) and stored as objects.

    The form never saves: ``cleaned_question()`` hands the values to the service, which
    decides between an in-place change and a new version.
    """

    options_en = forms.CharField(
        label=_("Options (English)"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=_("Choice questions only. One option per line."),
    )
    options_bn = forms.CharField(
        label=_("Options (Bangla)"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=_("Same order and count as the English options."),
    )

    class Meta:
        model = Question
        fields = ["category", "text", "text_bn", "question_type", "required", "applies_to"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].required = True
        self.fields["category"].queryset = QuestionCategory.objects.all()
        if self.instance.pk:
            labels = [option.get("en", "") for option in self.instance.options]
            self.initial.setdefault("options_en", "\n".join(labels))
            self.initial.setdefault(
                "options_bn", "\n".join(option.get("bn", "") for option in self.instance.options)
            )

    def clean(self):
        cleaned = super().clean()
        english, bangla = (
            _lines(cleaned.get("options_en", "")),
            _lines(cleaned.get("options_bn", "")),
        )
        try:
            cleaned["options"] = questions.build_options(
                english, bangla, self.instance.options if self.instance.pk else ()
            )
        except ValidationError as error:
            self.add_error("options_bn", error)
            return cleaned
        self.instance.options = cleaned["options"]
        return cleaned

    def _update_errors(self, errors):
        # The model validates ``options``; on this form they are typed in ``options_en``.
        error_dict = getattr(errors, "error_dict", {})
        if "options" in error_dict:
            error_dict["options_en"] = error_dict.pop("options")
        super()._update_errors(errors)

    def cleaned_question(self) -> dict:
        data = self.cleaned_data
        return {name: data[name] for name in (*questions.LOCKED_FIELDS, *questions.EDITABLE_FIELDS)}


class CategoryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = QuestionCategory
        fields = ["name", "name_bn", "order"]


class QuestionFilterForm(StyledFormMixin, forms.Form):
    q = forms.CharField(label=_("Search"), required=False, max_length=64)
    category = forms.ModelChoiceField(
        label=_("Category"),
        required=False,
        queryset=QuestionCategory.objects.all(),
        empty_label=_("All"),
    )
    question_type = forms.ChoiceField(
        label=_("Type"), required=False, choices=[("", _("All")), *QuestionType.choices]
    )
    applies_to = forms.ChoiceField(
        label=_("Applies to"), required=False, choices=[("", _("All")), *AppliesTo.choices]
    )
    active = forms.ChoiceField(
        label=_("Active"),
        required=False,
        choices=[("", _("All")), ("1", _("Yes")), ("0", _("No"))],
    )


class WindowForm(StyledFormMixin, forms.ModelForm):
    """Once a round has closed, its times and scope are read-only: results are released
    after the close, so the round cannot be reopened or moved."""

    LOCKED_AFTER_CLOSE = ("semester", "opens_at", "closes_at", "departments", "level_terms")

    class Meta:
        model = FeedbackWindow
        fields = [
            "semester",
            "name",
            "opens_at",
            "closes_at",
            "is_active",
            "departments",
            "level_terms",
        ]
        widgets = {"opens_at": DATETIME_INPUT, "closes_at": DATETIME_INPUT}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_locked = (
            self.instance.pk is not None
            and self.instance.status(timezone.now()) == WindowStatus.CLOSED
        )
        for name in ("opens_at", "closes_at"):
            self.fields[name].input_formats = [
                DATETIME_FORMAT,
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
            ]
        if self.is_locked:
            for name in self.LOCKED_AFTER_CLOSE:
                self.fields[name].disabled = True

    def clean(self):
        cleaned = super().clean()
        if self.is_locked or self.errors:
            return cleaned
        if cleaned["closes_at"] <= cleaned["opens_at"]:
            self.add_error("closes_at", _("The round must close after it opens."))
        elif cleaned["is_active"]:
            windows.ensure_no_overlap(cleaned, exclude_pk=self.instance.pk)
        return cleaned
