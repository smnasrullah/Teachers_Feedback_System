from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledFormMixin

DATE_INPUT = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class AuditFilterForm(StyledFormMixin, forms.Form):
    """The audit log's filters; all optional, all read from the query string."""

    actor = forms.CharField(label=_("Actor"), required=False, max_length=150)
    action = forms.CharField(label=_("Action"), required=False, max_length=64)
    object_type = forms.CharField(label=_("Object type"), required=False, max_length=100)
    object_id = forms.CharField(label=_("Object id"), required=False, max_length=64)
    date_from = forms.DateField(label=_("From"), required=False, widget=DATE_INPUT)
    date_to = forms.DateField(label=_("To"), required=False, widget=DATE_INPUT)

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("date_from"), cleaned.get("date_to")
        if start and end and end < start:
            self.add_error("date_to", _("The end date cannot be before the start date."))
        return cleaned
