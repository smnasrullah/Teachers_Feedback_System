"""Admin forms for the academic structure."""

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.academics.models import (
    Batch,
    Course,
    CourseOffering,
    Department,
    LevelTerm,
    Program,
    Semester,
)
from apps.academics.services import importers
from apps.accounts.forms import MAX_CODE_VALID_DAYS
from apps.accounts.models import TeacherProfile
from apps.core.forms import StyledFormMixin


class StyledModelForm(StyledFormMixin, forms.ModelForm):
    """A ModelForm with design-system widget classes."""


class DepartmentForm(StyledModelForm):
    class Meta:
        model = Department
        fields = ["code", "name", "name_bn", "is_active"]


class ProgramForm(StyledModelForm):
    class Meta:
        model = Program
        fields = ["department", "code", "name", "name_bn"]


class BatchForm(StyledModelForm):
    class Meta:
        model = Batch
        fields = ["program", "name"]


class LevelTermForm(StyledModelForm):
    class Meta:
        model = LevelTerm
        fields = ["name", "name_bn", "order"]


class SemesterForm(StyledModelForm):
    class Meta:
        model = Semester
        fields = ["name", "start_date", "end_date", "is_current"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "end_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }
        help_texts = {
            "is_current": _("Making this the current semester ends the previous one."),
        }


class CourseForm(StyledModelForm):
    class Meta:
        model = Course
        fields = [
            "code",
            "title",
            "title_bn",
            "credit",
            "course_type",
            "department",
            "program",
            "level_term",
            "is_elective",
        ]


class TeacherChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        registry = obj.registry
        return f"{registry.external_id} · {registry.full_name or '—'} ({registry.department.code})"


class CourseOfferingForm(StyledModelForm):
    teacher = TeacherChoiceField(
        label=_("teacher"),
        queryset=TeacherProfile.objects.select_related("registry__department").order_by(
            "registry__department__code", "id"
        ),
    )
    confirm_service_course = forms.BooleanField(
        label=_("Service course"),
        required=False,
        help_text=_(
            "Tick to confirm when the teacher belongs to another department than the course."
        ),
    )

    class Meta:
        model = CourseOffering
        fields = ["course", "semester", "teacher", "section"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["course"].queryset = Course.objects.select_related("department")
        if self.instance.pk:
            self.fields["confirm_service_course"].initial = self.is_service_course(
                self.instance.course, self.instance.teacher
            )

    @staticmethod
    def is_service_course(course, teacher) -> bool:
        return teacher.registry.department_id != course.department_id

    def clean(self):
        data = super().clean()
        course, teacher = data.get("course"), data.get("teacher")
        needs_confirmation = (
            course
            and teacher
            and self.is_service_course(course, teacher)
            and not data.get("confirm_service_course")
        )
        if needs_confirmation:
            self.add_error(
                "confirm_service_course",
                _(
                    "This teacher belongs to %(teacher_department)s but the course belongs "
                    "to %(course_department)s. Tick the box to confirm a service course."
                )
                % {
                    "teacher_department": teacher.registry.department.code,
                    "course_department": course.department.code,
                },
            )
        return data


class ImportUploadForm(StyledFormMixin, forms.Form):
    file = forms.FileField(
        label=_("CSV file"),
        help_text=_("UTF-8 (a BOM from Excel is fine), up to 5 MB and 10,000 rows."),
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}),
    )
    issue_codes = forms.BooleanField(
        label=_("Generate activation codes"),
        required=False,
        help_text=_("Codes are shown only once, in a downloaded CSV file, after the import."),
    )
    valid_days = forms.IntegerField(
        label=_("Codes valid for (days)"),
        min_value=1,
        max_value=MAX_CODE_VALID_DAYS,
        initial=importers.DEFAULT_CODE_VALID_DAYS,
        required=False,
    )

    def __init__(self, *args, importer, **kwargs):
        super().__init__(*args, **kwargs)
        if not importer.issues_codes:
            del self.fields["issue_codes"], self.fields["valid_days"]

    def clean_file(self):
        upload = self.cleaned_data["file"]
        return importers.decode(upload.read(importers.MAX_BYTES + 1))

    def options(self) -> dict:
        return {
            "issue_codes": bool(self.cleaned_data.get("issue_codes")),
            "valid_days": self.cleaned_data.get("valid_days") or importers.DEFAULT_CODE_VALID_DAYS,
        }


class AssignFilterForm(StyledFormMixin, forms.Form):
    semester = forms.ModelChoiceField(
        label=_("Semester"), queryset=Semester.objects.all(), required=False, empty_label=None
    )
    department = forms.ModelChoiceField(
        label=_("Department"),
        queryset=Department.objects.all(),
        required=False,
        empty_label=_("All"),
    )
