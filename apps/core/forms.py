"""Form helpers shared by every app."""

from django import forms


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
