"""Form helpers shared by every app."""

from django import forms
from django.core.exceptions import ValidationError

from apps.core.services import system_settings


class StyledFormMixin:
    """Gives every widget the design-system class that matches its kind."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = "check"
            elif isinstance(widget, forms.Select):
                css = "select"
            elif isinstance(widget, forms.Textarea):
                css = "textarea"
            else:
                css = "input"
            widget.attrs.setdefault("class", css)


def _setting_field(definition):
    options = {"label": definition.label, "help_text": definition.help}
    kind = definition.kind
    if kind == system_settings.Kind.BOOL:
        return forms.BooleanField(required=False, **options)
    if kind == system_settings.Kind.CHOICE:
        return forms.ChoiceField(choices=definition.choices, **options)
    attrs = {}
    if definition.minimum is not None:
        attrs["min"] = definition.minimum
    if definition.maximum is not None:
        attrs["max"] = definition.maximum
    if kind == system_settings.Kind.INT:
        return forms.IntegerField(widget=forms.NumberInput(attrs=attrs), **options)
    if kind == system_settings.Kind.FLOAT:
        attrs["step"] = "0.1"
        return forms.FloatField(widget=forms.NumberInput(attrs=attrs), **options)
    return forms.CharField(required=False, **options)


class SystemSettingsForm(StyledFormMixin, forms.Form):
    """One field per setting in ``system_settings.DEFINITIONS``. The service owns the limits;
    the form adds the browser hints and reports the service's verdict on each field."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for key, value in system_settings.current().items():
            self.initial[key] = ", ".join(map(str, value)) if isinstance(value, list) else value

    def clean(self):
        cleaned = super().clean()
        for key, definition in system_settings.DEFINITIONS.items():
            if key in self.errors:
                continue
            try:
                cleaned[key] = definition.normalise(cleaned.get(key))
            except ValidationError as error:
                self.add_error(key, error)
        return cleaned


# The fields come from the definitions, so they are attached after the class is built.
SystemSettingsForm.base_fields = {
    key: _setting_field(definition) for key, definition in system_settings.DEFINITIONS.items()
}
