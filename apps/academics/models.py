"""Academic structure: departments and programs down to semesters, courses and offerings,
then grades, results and the promotion rule (BLUEPRINT §3 F2)."""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
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


class GradeScale(models.Model):
    """One letter grade of the admin-editable scale and the points it is worth."""

    letter = models.CharField(_("letter grade"), max_length=4, unique=True)
    points = models.DecimalField(_("grade points"), max_digits=3, decimal_places=2)
    is_pass = models.BooleanField(
        _("passing grade"),
        default=True,
        help_text=_("A course with a failing grade must be retaken."),
    )

    class Meta:
        ordering = ["-points", "letter"]
        verbose_name = _("grade")
        verbose_name_plural = _("grade scale")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(points__gte=0),
                name="grade_points_not_negative",
                violation_error_message=_("Grade points cannot be negative."),
            )
        ]

    def __str__(self):
        return f"{self.letter} ({self.points})"


class Result(models.Model):
    """The grade of one enrollment. ``points`` is copied from the grade when it is set, so a
    later change to the grade scale never rewrites a published GPA."""

    enrollment = models.OneToOneField(
        "enrollment.Enrollment",
        on_delete=models.PROTECT,
        related_name="result",
        verbose_name=_("enrollment"),
    )
    grade = models.ForeignKey(
        GradeScale, on_delete=models.PROTECT, related_name="results", verbose_name=_("grade")
    )
    points = models.DecimalField(_("grade points"), max_digits=3, decimal_places=2)
    published = models.BooleanField(_("published"), default=False)

    class Meta:
        verbose_name = _("result")
        verbose_name_plural = _("results")

    def __str__(self):
        return f"Result({self.pk})"


class RetakePolicy(models.TextChoices):
    LATEST = "latest", _("The latest attempt counts")
    BEST = "best", _("The best attempt counts")


class PromotionRule(models.Model):
    """The one promotion rule (row ``pk=1``); ``current()`` creates it with the defaults."""

    max_failed_courses = models.PositiveSmallIntegerField(
        _("most failed courses allowed"),
        default=2,
        help_text=_("Courses whose counting attempt is a failing grade, from any term so far."),
    )
    min_cgpa = models.DecimalField(
        _("lowest CGPA allowed"), max_digits=3, decimal_places=2, default=Decimal("2.00")
    )
    min_credits = models.DecimalField(
        _("fewest credits to earn in the term"),
        max_digits=4,
        decimal_places=1,
        default=Decimal("0"),
        help_text=_("Credits of the courses passed in the semester being promoted from."),
    )
    retake_policy = models.CharField(
        _("retake policy"),
        max_length=16,
        choices=RetakePolicy.choices,
        default=RetakePolicy.LATEST,
        help_text=_("Which attempt of a retaken course counts in the CGPA."),
    )

    class Meta:
        verbose_name = _("promotion rule")
        verbose_name_plural = _("promotion rule")
        constraints = [
            models.CheckConstraint(condition=models.Q(pk=1), name="promotion_rule_singleton"),
            models.CheckConstraint(
                condition=models.Q(min_cgpa__gte=0, min_credits__gte=0),
                name="promotion_rule_not_negative",
                violation_error_message=_("The limits cannot be negative."),
            ),
        ]

    def __str__(self):
        return str(self._meta.verbose_name)

    @classmethod
    def current(cls) -> "PromotionRule":
        return cls.objects.get_or_create(pk=1)[0]


class Outcome(models.TextChoices):
    PROMOTE = "promote", _("Promote")
    PROMOTE_WITH_RETAKES = "promote_with_retakes", _("Promote with retakes")
    RETAIN = "retain", _("Retain")
    GRADUATE = "graduate", _("Graduate")


class PromotionOverride(models.Model):
    """The admin's choice for one student, replacing the computed outcome when applied."""

    student_profile = models.ForeignKey(
        "accounts.StudentProfile",
        on_delete=models.CASCADE,
        related_name="promotion_overrides",
        verbose_name=_("student"),
    )
    semester = models.ForeignKey(
        Semester,
        on_delete=models.CASCADE,
        related_name="promotion_overrides",
        verbose_name=_("semester"),
    )
    outcome = models.CharField(_("outcome"), max_length=24, choices=Outcome.choices)
    reason = models.CharField(_("reason"), max_length=300)

    class Meta:
        verbose_name = _("promotion override")
        verbose_name_plural = _("promotion overrides")
        constraints = [
            models.UniqueConstraint(
                fields=["student_profile", "semester"], name="promotion_override_unique"
            )
        ]

    def __str__(self):
        return f"PromotionOverride({self.pk})"


class PromotionDecision(models.Model):
    """What applying the promotion of ``semester`` did to one student. Its existence marks the
    student as done for that semester, which makes a second apply change nothing."""

    student_profile = models.ForeignKey(
        "accounts.StudentProfile",
        on_delete=models.PROTECT,
        related_name="promotion_decisions",
        verbose_name=_("student"),
    )
    semester = models.ForeignKey(
        Semester,
        on_delete=models.PROTECT,
        related_name="promotion_decisions",
        verbose_name=_("semester"),
    )
    outcome = models.CharField(_("outcome"), max_length=24, choices=Outcome.choices)
    computed_outcome = models.CharField(
        _("computed outcome"), max_length=24, choices=Outcome.choices
    )
    override_reason = models.CharField(_("override reason"), max_length=300, blank=True)
    from_level_term = models.ForeignKey(
        LevelTerm, on_delete=models.PROTECT, related_name="+", verbose_name=_("from level/term")
    )
    to_level_term = models.ForeignKey(
        LevelTerm, on_delete=models.PROTECT, related_name="+", verbose_name=_("to level/term")
    )
    term_gpa = models.DecimalField(_("term GPA"), max_digits=3, decimal_places=2)
    cgpa = models.DecimalField(_("CGPA"), max_digits=3, decimal_places=2)
    credits_earned = models.DecimalField(_("credits earned"), max_digits=5, decimal_places=1)
    failed_courses = models.PositiveSmallIntegerField(_("failed courses"))
    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
        verbose_name=_("applied by"),
    )
    applied_at = models.DateTimeField(_("applied at"), default=timezone.now)

    class Meta:
        verbose_name = _("promotion decision")
        verbose_name_plural = _("promotion decisions")
        constraints = [
            models.UniqueConstraint(
                fields=["student_profile", "semester"], name="promotion_decision_unique"
            )
        ]

    def __str__(self):
        return f"PromotionDecision({self.pk})"
