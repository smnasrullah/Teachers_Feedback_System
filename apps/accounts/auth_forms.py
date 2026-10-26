"""Forms for sign-up, login, two-factor, recovery and password change.

Validation here is user experience only; the services re-check everything.
"""

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import StyledForm
from apps.accounts.models import Theme
from apps.accounts.services import otp, signup, twofactor
from apps.accounts.services.passwords import validate_account_password
from apps.core.uploads import SafeImageField

NICKNAME_MAX_LENGTH = 50

OTP_ATTRS = {
    "inputmode": "numeric",
    "autocomplete": "one-time-code",
    "maxlength": "12",
    "class": "input otp-input num",
}


class ClaimForm(StyledForm):
    registry_id = forms.CharField(
        label=_("Student or teacher ID"),
        max_length=40,
        widget=forms.TextInput(attrs={"autocomplete": "off", "autocapitalize": "characters"}),
    )
    activation_code = forms.CharField(
        label=_("Activation code"),
        max_length=40,
        help_text=_("The code your department gave you, like XXXX-XXXX-XXXX."),
        widget=forms.TextInput(attrs={"autocomplete": "off", "autocapitalize": "characters"}),
    )


class ContactForm(StyledForm):
    contact = forms.CharField(
        label=_("E-mail address"),
        max_length=254,
        help_text=_("We send a 6-digit code here. It is also used to recover your account."),
        widget=forms.TextInput(attrs={"autocomplete": "email", "inputmode": "email"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if otp.sms_enabled():
            self.fields["contact"].label = _("E-mail address or phone number")

    def clean_contact(self):
        return signup.parse_contact(self.cleaned_data["contact"])


class OtpForm(StyledForm):
    code = forms.CharField(
        label=_("6-digit code"), max_length=12, widget=forms.TextInput(attrs=OTP_ATTRS)
    )

    def clean_code(self):
        code = otp.normalize_code(self.cleaned_data["code"])
        if len(code) != otp.CODE_LENGTH:
            raise ValidationError(_("Enter the 6-digit code."), code="invalid")
        return code


class NewPasswordForm(StyledForm):
    password1 = forms.CharField(
        label=_("New password"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label=_("Repeat the new password"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args, user=None, role=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.role = role

    def clean(self):
        cleaned = super().clean()
        first, second = cleaned.get("password1"), cleaned.get("password2")
        if first and second and first != second:
            self.add_error("password2", _("The two passwords do not match."))
        elif first:
            try:
                validate_account_password(first, self.user, role=self.role)
            except ValidationError as error:
                self.add_error("password1", error)
        return cleaned


class LoginForm(StyledForm):
    username = forms.CharField(
        label=_("Username"),
        max_length=64,
        widget=forms.TextInput(
            attrs={"autocomplete": "username", "autocapitalize": "none", "spellcheck": "false"}
        ),
    )
    password = forms.CharField(
        label=_("Password"),
        strip=False,
        max_length=256,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )


class SecondFactorForm(StyledForm):
    """A six-digit authenticator code, or (where allowed) a recovery code."""

    code = forms.CharField(
        label=_("Authenticator code"),
        max_length=32,
        widget=forms.TextInput(
            attrs={"autocomplete": "one-time-code", "inputmode": "text", "class": "input num"}
        ),
    )

    def clean_code(self):
        return twofactor.normalize_code(self.cleaned_data["code"])


class TotpCodeForm(SecondFactorForm):
    code = forms.CharField(
        label=_("6-digit code from the app"),
        max_length=12,
        widget=forms.TextInput(attrs=OTP_ATTRS),
    )


class ForgotPasswordForm(StyledForm):
    identifier = forms.CharField(
        label=_("Username or ID"),
        max_length=64,
        widget=forms.TextInput(attrs={"autocomplete": "username", "autocapitalize": "none"}),
    )


class ForgotUsernameForm(StyledForm):
    registry_id = forms.CharField(
        label=_("Student or teacher ID"),
        max_length=40,
        widget=forms.TextInput(attrs={"autocomplete": "off", "autocapitalize": "characters"}),
    )


class PasswordChangeForm(NewPasswordForm):
    current_password = forms.CharField(
        label=_("Current password"),
        strip=False,
        max_length=256,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )
    field_order = ["current_password", "password1", "password2"]

    def clean_current_password(self):
        password = self.cleaned_data["current_password"]
        if not self.user.check_password(password):
            raise ValidationError(_("The current password is not correct."), code="invalid")
        return password


class ConfirmPasswordForm(StyledForm):
    """Re-authentication before a sensitive 2FA change."""

    password = forms.CharField(
        label=_("Your password"),
        strip=False,
        max_length=256,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise ValidationError(_("The password is not correct."), code="invalid")
        return password


class ProfileForm(StyledForm):
    """The only things a person may change about themselves (nothing academic)."""

    nickname = forms.CharField(
        label=_("Nickname"),
        required=False,
        max_length=NICKNAME_MAX_LENGTH,
        help_text=_("Shown on your own pages. Do not use your real name or your ID."),
        widget=forms.TextInput(attrs={"autocomplete": "nickname"}),
    )
    avatar = SafeImageField(
        label=_("Picture"),
        required=False,
        widget=forms.FileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
        help_text=_("JPEG, PNG or WebP, up to 2 MB. It is re-encoded before it is stored."),
    )
    remove_avatar = forms.BooleanField(label=_("Remove my picture"), required=False)
    language = forms.ChoiceField(label=_("Language"), choices=settings.LANGUAGES)
    theme = forms.ChoiceField(label=_("Theme"), choices=Theme.choices)

    def clean_nickname(self):
        return " ".join(self.cleaned_data["nickname"].split())
