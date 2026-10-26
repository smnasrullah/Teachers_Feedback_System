from django import forms
from django.utils.translation import gettext_lazy as _

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
