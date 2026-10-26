from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledFormMixin
from apps.notifications.services import messages

SUBJECT_MAX = 200


class TemplateForm(StyledFormMixin, forms.Form):
    """The Admin's wording of one message in both languages. A blank field keeps the built-in
    text, which the field shows as its placeholder."""

    subject_en = forms.CharField(
        label=_("Subject (English)"), required=False, max_length=SUBJECT_MAX
    )
    body_en = forms.CharField(
        label=_("Message (English)"), required=False, widget=forms.Textarea(attrs={"rows": 5})
    )
    subject_bn = forms.CharField(
        label=_("Subject (Bangla)"), required=False, max_length=SUBJECT_MAX
    )
    body_bn = forms.CharField(
        label=_("Message (Bangla)"), required=False, widget=forms.Textarea(attrs={"rows": 5})
    )

    def __init__(self, kind: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.kind = kind
        for language in messages.LANGUAGES:
            built_in = messages.default_wording(kind, language)
            self.fields[f"subject_{language}"].widget.attrs["placeholder"] = built_in.subject
            self.fields[f"body_{language}"].widget.attrs["placeholder"] = built_in.body

    def clean(self):
        cleaned = super().clean()
        for name, value in list(cleaned.items()):
            if value and name not in self.errors:
                try:
                    messages.validate_placeholders(self.kind, value)
                except forms.ValidationError as error:
                    self.add_error(name, error)
        return cleaned


class SendTestForm(StyledFormMixin, forms.Form):
    language = forms.ChoiceField(
        label=_("Language"), choices=[("en", _("English")), ("bn", _("Bangla"))]
    )
