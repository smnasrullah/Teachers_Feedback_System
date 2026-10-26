"""Declarative description of the admin CRUD screens, one per academic model."""

from collections.abc import Callable
from dataclasses import dataclass

from django import forms
from django.db.models import Model, Q, QuerySet
from django.utils.translation import gettext_lazy as _

from apps.academics import forms as academic_forms
from apps.academics.models import (
    Batch,
    Course,
    CourseOffering,
    CourseType,
    Department,
    LevelTerm,
    Program,
    Semester,
)
from apps.core.forms import StyledFormMixin

YES_NO = [("", _("All")), ("1", _("Yes")), ("0", _("No"))]


def yes_no(value: bool) -> str:
    return str(_("Yes") if value else _("No"))


@dataclass(frozen=True)
class Column:
    label: str
    value: Callable[[Model], str]
    numeric: bool = False


@dataclass(frozen=True)
class Filter:
    """A list filter on ``lookup``: a model dropdown, or fixed ``choices`` (yes/no when boolean)."""

    name: str
    label: str
    lookup: str
    queryset: QuerySet | None = None
    choices: list | None = None
    boolean: bool = False

    def field(self) -> forms.Field:
        if self.queryset is not None:
            return forms.ModelChoiceField(
                label=self.label,
                required=False,
                queryset=self.queryset,
                empty_label=_("All"),
            )
        return forms.ChoiceField(label=self.label, required=False, choices=self.choices or YES_NO)

    def clean_value(self, value):
        return value == "1" if self.boolean else value


@dataclass(frozen=True)
class Screen:
    key: str
    model: type[Model]
    form_class: type[forms.ModelForm]
    title: str
    singular: str
    columns: tuple[Column, ...]
    search: tuple[str, ...] = ()
    filters: tuple[Filter, ...] = ()
    select_related: tuple[str, ...] = ()
    department_of: Callable[[Model], int | None] | None = None
    icon: str = "list"

    def queryset(self) -> QuerySet:
        return self.model.objects.select_related(*self.select_related)

    def filter_form_class(self) -> type[forms.Form]:
        fields = {f.name: f.field() for f in self.filters}
        if self.search:
            fields = {
                "q": forms.CharField(label=_("Search"), required=False, max_length=64)
            } | fields
        return type("FilterForm", (StyledFormMixin, forms.Form), fields)

    def apply_filters(self, queryset: QuerySet, data: dict) -> QuerySet:
        term = (data.get("q") or "").strip()
        if term:
            query = Q()
            for lookup in self.search:
                query |= Q(**{f"{lookup}__icontains": term})
            queryset = queryset.filter(query)
        for item in self.filters:
            value = data.get(item.name)
            if value not in (None, ""):
                queryset = queryset.filter(**{item.lookup: item.clean_value(value)})
        return queryset


SCREENS: dict[str, Screen] = {
    screen.key: screen
    for screen in (
        Screen(
            key="departments",
            model=Department,
            form_class=academic_forms.DepartmentForm,
            title=_("Departments"),
            singular=_("department"),
            columns=(
                Column(_("Code"), lambda o: o.code),
                Column(_("Name"), lambda o: o.name),
                Column(_("Name (Bangla)"), lambda o: o.name_bn or "—"),
                Column(_("Active"), lambda o: yes_no(o.is_active)),
            ),
            search=("code", "name", "name_bn"),
            filters=(Filter("active", _("Active"), "is_active", boolean=True),),
            department_of=lambda o: o.pk,
            icon="flag",
        ),
        Screen(
            key="programs",
            model=Program,
            form_class=academic_forms.ProgramForm,
            title=_("Programs"),
            singular=_("program"),
            columns=(
                Column(_("Department"), lambda o: o.department.code),
                Column(_("Code"), lambda o: o.code),
                Column(_("Name"), lambda o: o.name),
                Column(_("Name (Bangla)"), lambda o: o.name_bn or "—"),
            ),
            search=("code", "name", "name_bn"),
            filters=(
                Filter(
                    "department", _("Department"), "department", queryset=Department.objects.all()
                ),
            ),
            select_related=("department",),
            department_of=lambda o: o.department_id,
            icon="book",
        ),
        Screen(
            key="batches",
            model=Batch,
            form_class=academic_forms.BatchForm,
            title=_("Batches"),
            singular=_("batch"),
            columns=(
                Column(_("Department"), lambda o: o.program.department.code),
                Column(_("Program"), lambda o: o.program.code),
                Column(_("Name"), lambda o: o.name),
            ),
            search=("name",),
            filters=(
                Filter(
                    "program",
                    _("Program"),
                    "program",
                    queryset=Program.objects.select_related("department"),
                ),
            ),
            select_related=("program__department",),
            department_of=lambda o: o.program.department_id,
            icon="users",
        ),
        Screen(
            key="level-terms",
            model=LevelTerm,
            form_class=academic_forms.LevelTermForm,
            title=_("Levels/terms"),
            singular=_("level/term"),
            columns=(
                Column(_("Order"), lambda o: str(o.order), numeric=True),
                Column(_("Name"), lambda o: o.name),
                Column(_("Name (Bangla)"), lambda o: o.name_bn or "—"),
            ),
            search=("name", "name_bn"),
            icon="list",
        ),
        Screen(
            key="semesters",
            model=Semester,
            form_class=academic_forms.SemesterForm,
            title=_("Semesters"),
            singular=_("semester"),
            columns=(
                Column(_("Name"), lambda o: o.name),
                Column(_("Start date"), lambda o: o.start_date.isoformat(), numeric=True),
                Column(_("End date"), lambda o: o.end_date.isoformat(), numeric=True),
                Column(_("Current"), lambda o: yes_no(o.is_current)),
            ),
            search=("name",),
            filters=(Filter("current", _("Current"), "is_current", boolean=True),),
            icon="calendar",
        ),
        Screen(
            key="courses",
            model=Course,
            form_class=academic_forms.CourseForm,
            title=_("Courses"),
            singular=_("course"),
            columns=(
                Column(_("Code"), lambda o: o.code),
                Column(_("Title"), lambda o: o.title),
                Column(_("Credit"), lambda o: f"{o.credit:g}", numeric=True),
                Column(_("Type"), lambda o: o.get_course_type_display()),
                Column(_("Department"), lambda o: o.department.code),
                Column(_("Program"), lambda o: o.program.code),
                Column(_("Level/term"), lambda o: o.level_term.name),
                Column(_("Elective"), lambda o: yes_no(o.is_elective)),
            ),
            search=("code", "title", "title_bn"),
            filters=(
                Filter(
                    "department", _("Department"), "department", queryset=Department.objects.all()
                ),
                Filter(
                    "level_term", _("Level/term"), "level_term", queryset=LevelTerm.objects.all()
                ),
                Filter(
                    "type", _("Type"), "course_type", choices=[("", _("All")), *CourseType.choices]
                ),
                Filter("elective", _("Elective"), "is_elective", boolean=True),
            ),
            select_related=("department", "program", "level_term"),
            department_of=lambda o: o.department_id,
            icon="book",
        ),
        Screen(
            key="offerings",
            model=CourseOffering,
            form_class=academic_forms.CourseOfferingForm,
            title=_("Course offerings"),
            singular=_("course offering"),
            columns=(
                Column(_("Course"), lambda o: f"{o.course.code} {o.course.title}"),
                Column(_("Semester"), lambda o: o.semester.name),
                Column(_("Section"), lambda o: o.section or "—"),
                Column(_("Teacher"), lambda o: o.teacher.registry.full_name or "—"),
                Column(_("Department"), lambda o: o.course.department.code),
            ),
            search=("course__code", "course__title", "section"),
            filters=(
                Filter("semester", _("Semester"), "semester", queryset=Semester.objects.all()),
                Filter(
                    "department",
                    _("Department"),
                    "course__department",
                    queryset=Department.objects.all(),
                ),
            ),
            select_related=("course__department", "semester", "teacher__registry"),
            department_of=lambda o: o.course.department_id,
            icon="calendar",
        ),
    )
}
