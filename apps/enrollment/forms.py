"""Admin forms for enrolling students."""

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.academics.models import CourseOffering, Department, LevelTerm, Program
from apps.academics.services import semesters
from apps.accounts.forms import StyledForm
from apps.accounts.models import StudentProfile, registry_index
from apps.enrollment.models import EnrollmentStatus


class CurrentOfferingsMixin:
    """Limits ``offering`` to today's semester, worked out per form (never at import time)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["offering"].queryset = CourseOffering.objects.filter(
            semester__in=semesters.ongoing()
        ).select_related("course", "semester")


class GroupForm(StyledForm):
    program = forms.ModelChoiceField(
        label=_("Program"), queryset=Program.objects.select_related("department")
    )
    level_term = forms.ModelChoiceField(label=_("Level/term"), queryset=LevelTerm.objects.all())


class EnrollForm(CurrentOfferingsMixin, StyledForm):
    student_id = forms.CharField(label=_("Student ID"), max_length=32)
    offering = forms.ModelChoiceField(
        label=_("Course offering"),
        queryset=CourseOffering.objects.none(),
        help_text=_("Offerings of the current semester."),
    )
    status = forms.ChoiceField(
        label=_("Status"), choices=EnrollmentStatus.choices, initial=EnrollmentStatus.REGULAR
    )

    def clean_student_id(self):
        profile = StudentProfile.objects.filter(
            registry__external_id_index=registry_index(self.cleaned_data["student_id"])
        ).first()
        if profile is None:
            raise forms.ValidationError(_("No registered student has this ID."))
        return profile


class EnrollmentFilterForm(CurrentOfferingsMixin, StyledForm):
    offering = forms.ModelChoiceField(
        label=_("Course offering"),
        required=False,
        empty_label=_("All"),
        queryset=CourseOffering.objects.none(),
    )
    student_id = forms.CharField(label=_("Student ID"), required=False, max_length=32)
    status = forms.ChoiceField(
        label=_("Status"), required=False, choices=[("", _("All")), *EnrollmentStatus.choices]
    )


class MissingFilterForm(StyledForm):
    department = forms.ModelChoiceField(
        label=_("Department"),
        required=False,
        empty_label=_("All"),
        queryset=Department.objects.all(),
    )
    level_term = forms.ModelChoiceField(
        label=_("Level/term"),
        required=False,
        empty_label=_("All"),
        queryset=LevelTerm.objects.all(),
    )
