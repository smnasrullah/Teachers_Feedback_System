"""Admin forms for the ID registry, bulk actions, roles and HOD assignment."""

from django import forms
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.academics.models import Batch, Department, LevelTerm, Program
from apps.accounts.models import AcademicStatus, IdRegistry, IdType, RegistryStatus, registry_index
from apps.accounts.services import registry as registry_service
from apps.accounts.services.identifiers import clean_registry_id
from apps.accounts.services.roles import CHANGEABLE_ROLES
from apps.core.forms import StyledFormMixin
from apps.core.permissions import Role
from apps.core.uploads import SafeImageField

DEFAULT_CODE_VALID_DAYS = 14
MAX_CODE_VALID_DAYS = 90


class StyledForm(StyledFormMixin, forms.Form):
    """A plain form with design-system widget classes."""


class RegistryFilterForm(StyledForm):
    q = forms.CharField(
        label=_("Search"),
        required=False,
        max_length=64,
        help_text=_("Exact ID or username. Names are encrypted and cannot be searched."),
    )
    id_type = forms.ChoiceField(
        label=_("Type"), required=False, choices=[("", _("All types")), *IdType.choices]
    )
    status = forms.ChoiceField(
        label=_("Status"),
        required=False,
        choices=[("", _("All statuses")), *RegistryStatus.choices],
    )
    department = forms.ModelChoiceField(
        label=_("Department"),
        required=False,
        queryset=Department.objects.all(),
        empty_label=_("All departments"),
    )

    def entries(self):
        """Registry rows matching the filters (call only on a valid form)."""
        entries = IdRegistry.objects.select_related("department", "claimed_by")
        data = self.cleaned_data
        if data.get("q"):
            term = data["q"].strip()
            entries = entries.filter(
                Q(external_id_index=registry_index(term)) | Q(claimed_by__username=term.lower())
            )
        for name in ("id_type", "status", "department"):
            if data.get(name):
                entries = entries.filter(**{name: data[name]})
        return entries


class BulkActionForm(StyledForm):
    ACTION_CODES = "generate_codes"
    ACTION_REVOKE = "revoke"
    ACTION_ACTIVATE = "activate"

    action = forms.ChoiceField(
        label=_("Action"),
        choices=[
            (ACTION_CODES, _("Generate activation codes")),
            (ACTION_REVOKE, _("Revoke")),
            (ACTION_ACTIVATE, _("Re-activate")),
        ],
    )
    valid_days = forms.IntegerField(
        label=_("Codes valid for (days)"),
        min_value=1,
        max_value=MAX_CODE_VALID_DAYS,
        initial=DEFAULT_CODE_VALID_DAYS,
        required=False,
    )
    select_all_matching = forms.BooleanField(
        label=_("Apply to every entry matching the current filters"), required=False
    )

    def __init__(self, data=None, *args, **kwargs):
        super().__init__(data, *args, **kwargs)
        self.filter_form = RegistryFilterForm(data)
        self.selected_ids: list[int] = []
        if data is not None:
            self.selected_ids = [int(value) for value in data.getlist("ids") if value.isdigit()]

    def clean_valid_days(self):
        return self.cleaned_data.get("valid_days") or DEFAULT_CODE_VALID_DAYS

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("select_all_matching"):
            if not self.filter_form.is_valid():
                raise forms.ValidationError(_("The filters are not valid."))
        elif not self.selected_ids:
            raise forms.ValidationError(_("Select at least one entry."))
        return cleaned

    def entries(self):
        if self.cleaned_data["select_all_matching"]:
            return self.filter_form.entries()
        return IdRegistry.objects.filter(pk__in=self.selected_ids)


class RegistryEntryForm(StyledForm):
    """Fields shared by student and teacher entries; subclasses add their profile fields."""

    id_type: str
    profile_fields: tuple[str, ...]

    external_id = forms.CharField(label=_("ID"), max_length=32)
    full_name = forms.CharField(label=_("Full name (optional)"), required=False, max_length=150)
    department = forms.ModelChoiceField(
        label=_("Department"), queryset=Department.objects.filter(is_active=True)
    )

    def __init__(self, *args, registry: IdRegistry | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.registry = registry
        if registry is not None:
            self.fields["external_id"].disabled = bool(registry.claimed_by_id)
            self.fields["external_id"].help_text = (
                _("The ID of a claimed entry cannot be changed.") if registry.claimed_by_id else ""
            )
            if not self.is_bound:
                self.initial = self._initial_from(registry)

    def _initial_from(self, registry: IdRegistry) -> dict:
        initial = {
            "external_id": registry.external_id,
            "full_name": registry.full_name or "",
            "department": registry.department_id,
        }
        profile = getattr(registry, f"{self.id_type}_profile")
        initial.update({name: getattr(profile, name) for name in self.profile_fields})
        return initial

    def clean_external_id(self):
        external_id = clean_registry_id(self.cleaned_data["external_id"])
        exclude_pk = self.registry.pk if self.registry else None
        if registry_service.id_is_taken(self.id_type, external_id, exclude_pk=exclude_pk):
            raise forms.ValidationError(_("This ID is already registered."), code="duplicate_id")
        return external_id

    def profile_values(self) -> dict:
        return {name: self.cleaned_data[name] for name in self.profile_fields}

    def save(self, *, actor, request=None):
        data = self.cleaned_data
        common = {
            "external_id": data["external_id"],
            "full_name": data["full_name"],
            "department": data["department"],
            "profile": self.profile_values(),
            "actor": actor,
            "request": request,
        }
        if self.registry is None:
            return registry_service.register(self.id_type, **common)
        registry_service.update(self.registry, **common)
        return self.registry


class StudentEntryForm(RegistryEntryForm):
    id_type = IdType.STUDENT
    profile_fields = ("program", "batch", "level_term", "section", "academic_status")

    program = forms.ModelChoiceField(
        label=_("Program"), queryset=Program.objects.select_related("department")
    )
    batch = forms.ModelChoiceField(
        label=_("Batch"), queryset=Batch.objects.select_related("program"), required=False
    )
    level_term = forms.ModelChoiceField(label=_("Level/Term"), queryset=LevelTerm.objects.all())
    section = forms.CharField(label=_("Section"), required=False, max_length=16)
    academic_status = forms.ChoiceField(
        label=_("Academic status"), choices=AcademicStatus.choices, initial=AcademicStatus.ACTIVE
    )

    def clean(self):
        cleaned = super().clean()
        department, program, batch = (cleaned.get(n) for n in ("department", "program", "batch"))
        if department and program and program.department_id != department.pk:
            self.add_error("program", _("This program belongs to a different department."))
        if program and batch and batch.program_id != program.pk:
            self.add_error("batch", _("This batch belongs to a different program."))
        return cleaned


class TeacherEntryForm(RegistryEntryForm):
    id_type = IdType.TEACHER
    profile_fields = ("designation", "photo")

    designation = forms.CharField(label=_("Designation"), required=False, max_length=100)
    photo = SafeImageField(
        label=_("Photo"),
        required=False,
        widget=forms.FileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
        help_text=_("JPEG, PNG or WebP, up to 2 MB. It is re-encoded before it is stored."),
    )

    def _initial_from(self, registry):
        initial = super()._initial_from(registry)
        initial.pop("photo", None)
        return initial


ENTRY_FORMS = {IdType.STUDENT: StudentEntryForm, IdType.TEACHER: TeacherEntryForm}


class HodForm(StyledForm):
    department = forms.ModelChoiceField(
        label=_("Department to head"), queryset=Department.objects.filter(is_active=True)
    )


class RoleForm(StyledForm):
    role = forms.ChoiceField(
        label=_("Role"), choices=[(role, Role(role).label) for role in CHANGEABLE_ROLES]
    )


class ResetAccessForm(StyledForm):
    """Lost phone: how long the new activation code lasts and how it is handed over."""

    OUTPUT_PAGE = "page"
    OUTPUT_CSV = "csv"

    valid_days = forms.IntegerField(
        label=_("Code valid for (days)"),
        min_value=1,
        max_value=MAX_CODE_VALID_DAYS,
        initial=DEFAULT_CODE_VALID_DAYS,
    )
    output = forms.ChoiceField(
        label=_("Hand the code over as"),
        choices=[(OUTPUT_PAGE, _("A printable page")), (OUTPUT_CSV, _("A CSV file"))],
        initial=OUTPUT_PAGE,
    )


class UserFilterForm(StyledForm):
    q = forms.CharField(
        label=_("Search"), required=False, max_length=64, help_text=_("Username or nickname")
    )
    role = forms.ChoiceField(
        label=_("Role"), required=False, choices=[("", _("All roles")), *Role.choices]
    )
