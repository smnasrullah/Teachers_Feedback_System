from django import forms
from django.utils.translation import gettext_lazy as _

from apps.academics.models import Department, LevelTerm, Semester
from apps.core.forms import StyledFormMixin
from apps.feedback.models import FeedbackWindow
from apps.reports.models import NOTE_MAX_LENGTH


class ActionNoteForm(forms.Form):
    text = forms.CharField(
        label=_("Action taken"),
        max_length=NOTE_MAX_LENGTH,
        required=False,
        strip=True,
        widget=forms.Textarea(attrs={"rows": 4, "class": "textarea", "maxlength": NOTE_MAX_LENGTH}),
        help_text=_("Visible to your head of department."),
    )


class UniversityFilterForm(StyledFormMixin, forms.Form):
    """The Admin analytics filters; each is optional and checked against the database."""

    semester = forms.ModelChoiceField(
        Semester.objects.all(), required=False, label=_("Semester"), empty_label=_("All semesters")
    )
    department = forms.ModelChoiceField(
        Department.objects.filter(is_active=True),
        required=False,
        label=_("Department"),
        empty_label=_("All departments"),
    )
    level_term = forms.ModelChoiceField(
        LevelTerm.objects.all(),
        required=False,
        label=_("Level/term"),
        empty_label=_("All levels/terms"),
    )
    round = forms.ModelChoiceField(
        FeedbackWindow.objects.filter(is_active=True).select_related("semester"),
        required=False,
        label=_("Round"),
        empty_label=_("Latest round"),
    )

    def clean(self):
        cleaned = super().clean()
        semester, window = cleaned.get("semester"), cleaned.get("round")
        if semester and window and window.semester_id != semester.pk:
            self.add_error("round", _("This round belongs to another semester."))
        return cleaned
