"""Academic structure: departments and programs down to semesters, courses and offerings."""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


class Department(models.Model):
    code = models.CharField(_("code"), max_length=16, unique=True)
    name = models.CharField(_("name"), max_length=150)
    name_bn = models.CharField(_("name (Bangla)"), max_length=150, blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = _("department")
        verbose_name_plural = _("departments")

    def __str__(self):
        return self.code


class Program(models.Model):
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="programs", verbose_name=_("department")
    )
    code = models.CharField(_("code"), max_length=16)
    name = models.CharField(_("name"), max_length=150)
    name_bn = models.CharField(_("name (Bangla)"), max_length=150, blank=True)

    class Meta:
        ordering = ["department__code", "code"]
        verbose_name = _("program")
        verbose_name_plural = _("programs")
        constraints = [
            models.UniqueConstraint(
                fields=["department", "code"],
                name="program_unique_code",
                violation_error_message=_("This department already has a program with this code."),
            )
        ]

    def __str__(self):
        return f"{self.department.code} {self.code}"


class Batch(models.Model):
    program = models.ForeignKey(
        Program, on_delete=models.PROTECT, related_name="batches", verbose_name=_("program")
    )
    name = models.CharField(_("name"), max_length=50)

    class Meta:
        ordering = ["program__code", "-name"]
        verbose_name = _("batch")
        verbose_name_plural = _("batches")
        constraints = [
            models.UniqueConstraint(
                fields=["program", "name"],
                name="batch_unique_name",
                violation_error_message=_("This program already has a batch with this name."),
            )
        ]

    def __str__(self):
        return f"{self.program.code} {self.name}"


class LevelTerm(models.Model):
    """One step of the curriculum (for example "Level 2, Term 1").

    How many exist is data, not code: the admin defines as many ordered rows as the
    university's scheme needs. ``order`` is unique and drives promotion order.
    """

    name = models.CharField(_("name"), max_length=50)
    name_bn = models.CharField(_("name (Bangla)"), max_length=50, blank=True)
    order = models.PositiveSmallIntegerField(_("order"), unique=True)

    class Meta:
        ordering = ["order"]
        verbose_name = _("level/term")
        verbose_name_plural = _("levels/terms")

    def __str__(self):
        return self.name


class Semester(models.Model):
    name = models.CharField(_("name"), max_length=50, unique=True)
    start_date = models.DateField(_("start date"))
    end_date = models.DateField(_("end date"))
    is_current = models.BooleanField(_("current semester"), default=False)

    class Meta:
        ordering = ["-start_date"]
        verbose_name = _("semester")
        verbose_name_plural = _("semesters")
        constraints = [
            models.UniqueConstraint(
                fields=["is_current"],
                condition=models.Q(is_current=True),
                name="one_current_semester",
                violation_error_message=_("Only one semester can be the current one."),
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__gt=models.F("start_date")),
                name="semester_ends_after_start",
                violation_error_message=_("The end date must be after the start date."),
            ),
        ]

    def __str__(self):
        return self.name

    def validate_constraints(self, exclude=None):
        # Saving a current semester demotes the previous one (catalog.save), so form
        # validation must not reject it; the database constraint still guarantees one.
        super().validate_constraints(exclude={*(exclude or ()), "is_current"})


class CourseType(models.TextChoices):
    THEORY = "theory", _("Theory")
    LAB = "lab", _("Lab")


class Course(models.Model):
    code = models.CharField(_("code"), max_length=20)
    title = models.CharField(_("title"), max_length=200)
    title_bn = models.CharField(_("title (Bangla)"), max_length=200, blank=True)
    credit = models.DecimalField(_("credit"), max_digits=3, decimal_places=1)
    course_type = models.CharField(
        _("type"), max_length=16, choices=CourseType.choices, default=CourseType.THEORY
    )
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="courses", verbose_name=_("department")
    )
    program = models.ForeignKey(
        Program, on_delete=models.PROTECT, related_name="courses", verbose_name=_("program")
    )
    level_term = models.ForeignKey(
        LevelTerm, on_delete=models.PROTECT, related_name="courses", verbose_name=_("level/term")
    )
    is_elective = models.BooleanField(_("elective"), default=False)

    class Meta:
        ordering = ["department__code", "code"]
        verbose_name = _("course")
        verbose_name_plural = _("courses")
        constraints = [
            models.UniqueConstraint(
                fields=["department", "code"],
                name="course_unique_code",
                violation_error_message=_("This department already has a course with this code."),
            ),
            models.CheckConstraint(
                condition=models.Q(credit__gt=0),
                name="course_credit_positive",
                violation_error_message=_("The credit must be greater than zero."),
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.title}"

    def clean(self):
        super().clean()
        if (
            self.program_id
            and self.department_id
            and self.program.department_id != self.department_id
        ):
            raise ValidationError(
                {"program": _("The program must belong to the course's department.")}
            )


class CourseOffering(models.Model):
    """A course taught in one semester by one teacher; its department is the course's."""

    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, related_name="offerings", verbose_name=_("course")
    )
    semester = models.ForeignKey(
        Semester, on_delete=models.PROTECT, related_name="offerings", verbose_name=_("semester")
    )
    teacher = models.ForeignKey(
        "accounts.TeacherProfile",
        on_delete=models.PROTECT,
        related_name="offerings",
        verbose_name=_("teacher"),
    )
    section = models.CharField(_("section"), max_length=16, blank=True)

    class Meta:
        ordering = ["-semester__start_date", "course__code", "section"]
        verbose_name = _("course offering")
        verbose_name_plural = _("course offerings")
        constraints = [
            models.UniqueConstraint(
                fields=["course", "semester", "section"],
                name="offering_unique_section",
                violation_error_message=_(
                    "This course is already offered in this semester with this section."
                ),
            )
        ]

    def __str__(self):
        label = f"{self.course.code} · {self.semester.name}"
        return f"{label} ({self.section})" if self.section else label

    @property
    def department(self) -> Department:
        return self.course.department
