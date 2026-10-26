"""Question bank, feedback rounds and the anonymous answers (BLUEPRINT §5.1-§5.2).

Anonymity is structural. ``FeedbackResponse`` and ``Answer`` know only the offering, the
round and the question: random UUID keys, no time, no IP, no path to a person.
``SubmissionReceipt`` alone records who submitted, and it holds no content and no time.
"""

import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.academics.models import CourseType
from apps.core.encryption import EncryptedTextField, TimelessEncryptedTextField

# Ratings and agreement questions use one five-point scale.
SCALE_MIN, SCALE_MAX = 1, 5
CHOICE_VALUE_MAX_LENGTH = 50


class QuestionType(models.TextChoices):
    RATING = "rating", _("Rating (1-5)")
    LIKERT = "likert", _("Agreement (1-5)")
    CHOICE = "choice", _("Choice")
    YES_NO = "yesno", _("Yes / no")
    TEXT = "text", _("Text")


class AppliesTo(models.TextChoices):
    ALL = "all", _("All courses")
    THEORY = CourseType.THEORY.value, _("Theory courses")
    LAB = CourseType.LAB.value, _("Lab courses")


class WindowStatus(models.TextChoices):
    UPCOMING = "upcoming", _("Upcoming")
    OPEN = "open", _("Open")
    CLOSED = "closed", _("Closed")


class QuestionCategory(models.Model):
    """A topic that groups questions (Teaching, Lab, ...); the admin can add more."""

    name = models.CharField(_("name"), max_length=100, unique=True)
    name_bn = models.CharField(_("name (Bangla)"), max_length=100, blank=True)
    order = models.PositiveSmallIntegerField(_("order"), default=0)

    class Meta:
        ordering = ["order", "pk"]
        verbose_name = _("question category")
        verbose_name_plural = _("question categories")

    def __str__(self):
        return self.name


class QuestionQuerySet(models.QuerySet):
    def for_course_type(self, course_type):
        """The active questions asked about courses of ``course_type``, in form order."""
        return self.filter(is_active=True, applies_to__in=[AppliesTo.ALL, course_type]).order_by(
            "order", "pk"
        )

    def for_offering(self, offering):
        """The active questions asked about ``offering``, in form order."""
        return self.for_course_type(offering.course.course_type)


class Question(models.Model):
    """One question of the bank. Answers point at the exact version they answered, so a
    changed question is a new row that ``supersedes`` the old one."""

    text = models.CharField(_("text"), max_length=500)
    text_bn = models.CharField(_("text (Bangla)"), max_length=500, blank=True)
    category = models.ForeignKey(
        QuestionCategory,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="questions",
        verbose_name=_("category"),
    )
    question_type = models.CharField(_("type"), max_length=16, choices=QuestionType.choices)
    options = models.JSONField(
        _("options"),
        default=list,
        blank=True,
        help_text=_('Choice questions only: a list of {"value", "en", "bn"} objects.'),
    )
    required = models.BooleanField(_("required"), default=True)
    order = models.PositiveSmallIntegerField(_("order"), default=0)
    is_active = models.BooleanField(_("active"), default=True)
    applies_to = models.CharField(
        _("applies to"), max_length=16, choices=AppliesTo.choices, default=AppliesTo.ALL
    )
    version = models.PositiveSmallIntegerField(_("version"), default=1)
    supersedes = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="superseded_by",
        verbose_name=_("replaces"),
    )

    objects = QuestionQuerySet.as_manager()

    class Meta:
        ordering = ["order", "pk"]
        verbose_name = _("question")
        verbose_name_plural = _("questions")
        constraints = [
            models.CheckConstraint(condition=models.Q(version__gte=1), name="question_version")
        ]

    def __str__(self):
        return self.text

    def clean(self):
        super().clean()
        if self.question_type != QuestionType.CHOICE:
            if self.options:
                raise ValidationError({"options": _("Only choice questions have options.")})
            return
        values = [
            option.get("value") if isinstance(option, dict) else None for option in self.options
        ]
        if (
            len(values) < 2
            or len(set(values)) != len(values)
            or not all(
                isinstance(value, str) and 0 < len(value) <= CHOICE_VALUE_MAX_LENGTH
                for value in values
            )
        ):
            raise ValidationError(
                {"options": _("A choice question needs at least two options with distinct values.")}
            )

    def option_values(self) -> frozenset[str]:
        return frozenset(
            option["value"]
            for option in self.options
            if isinstance(option, dict) and isinstance(option.get("value"), str)
        )


class FeedbackWindow(models.Model):
    """One feedback round of a semester. Open or closed is computed from the datetimes at
    request time; an optional scope limits it to some departments or levels/terms."""

    semester = models.ForeignKey(
        "academics.Semester",
        on_delete=models.PROTECT,
        related_name="feedback_windows",
        verbose_name=_("semester"),
    )
    name = models.CharField(_("name"), max_length=100)
    opens_at = models.DateTimeField(_("opens at"))
    closes_at = models.DateTimeField(_("closes at"))
    is_active = models.BooleanField(_("active"), default=True)
    departments = models.ManyToManyField(
        "academics.Department",
        blank=True,
        related_name="feedback_windows",
        verbose_name=_("departments"),
        help_text=_("Leave empty for every department (the course's department counts)."),
    )
    level_terms = models.ManyToManyField(
        "academics.LevelTerm",
        blank=True,
        related_name="feedback_windows",
        verbose_name=_("levels/terms"),
        help_text=_("Leave empty for every level/term (the course's level/term counts)."),
    )

    class Meta:
        ordering = ["-opens_at"]
        verbose_name = _("feedback round")
        verbose_name_plural = _("feedback rounds")
        constraints = [
            models.UniqueConstraint(
                fields=["semester", "name"],
                name="feedback_window_unique_name",
                violation_error_message=_("This semester already has a round with this name."),
            ),
            models.CheckConstraint(
                condition=models.Q(closes_at__gt=models.F("opens_at")),
                name="feedback_window_closes_after_opening",
                violation_error_message=_("The round must close after it opens."),
            ),
        ]

    def __str__(self):
        return self.name

    def status(self, now) -> str:
        """Upcoming, open or closed by the datetimes alone; ``is_active`` is separate."""
        if now >= self.closes_at:
            return WindowStatus.CLOSED
        return WindowStatus.UPCOMING if now < self.opens_at else WindowStatus.OPEN

    def is_open(self, now) -> bool:
        return self.is_active and self.status(now) == WindowStatus.OPEN

    def has_closed(self, now) -> bool:
        return self.status(now) == WindowStatus.CLOSED

    def covers(self, offering) -> bool:
        """Whether ``offering`` belongs to this round (semester and optional scope)."""
        course = offering.course
        if offering.semester_id != self.semester_id:
            return False
        # ``.all()`` so a prefetch (the student dashboard checks many rounds) is used.
        departments = {department.pk for department in self.departments.all()}
        if departments and course.department_id not in departments:
            return False
        level_terms = {level_term.pk for level_term in self.level_terms.all()}
        return not level_terms or course.level_term_id in level_terms


class SubmissionReceipt(models.Model):
    """Who has submitted for which offering in which round: the one-time lock, the pending
    list and reminders. It holds no content and no time."""

    student_profile = models.ForeignKey(
        "accounts.StudentProfile",
        on_delete=models.PROTECT,
        related_name="feedback_receipts",
        verbose_name=_("student"),
    )
    offering = models.ForeignKey(
        "academics.CourseOffering",
        on_delete=models.PROTECT,
        related_name="feedback_receipts",
        verbose_name=_("course offering"),
    )
    window = models.ForeignKey(
        FeedbackWindow,
        on_delete=models.PROTECT,
        related_name="receipts",
        verbose_name=_("feedback round"),
    )

    class Meta:
        verbose_name = _("submission receipt")
        verbose_name_plural = _("submission receipts")
        indexes = [models.Index(fields=["window", "offering"], name="receipt_window_offering")]
        constraints = [
            models.UniqueConstraint(
                fields=["student_profile", "offering", "window"], name="one_receipt_per_round"
            )
        ]

    def __str__(self):
        return f"SubmissionReceipt({self.pk})"


class FeedbackResponse(models.Model):
    """One anonymous submission: only the offering and the round, never who or when."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    offering = models.ForeignKey(
        "academics.CourseOffering",
        on_delete=models.PROTECT,
        related_name="feedback_responses",
        verbose_name=_("course offering"),
    )
    window = models.ForeignKey(
        FeedbackWindow,
        on_delete=models.PROTECT,
        related_name="responses",
        verbose_name=_("feedback round"),
    )

    class Meta:
        verbose_name = _("feedback response")
        verbose_name_plural = _("feedback responses")
        indexes = [
            models.Index(fields=["offering", "window"], name="response_offering_window"),
            models.Index(fields=["window", "offering"], name="response_window_offering"),
        ]

    def __str__(self):
        return f"FeedbackResponse({self.pk})"


class ModerationStatus(models.TextChoices):
    UNREVIEWED = "unreviewed", _("Not reviewed")
    REPORTED = "reported", _("Reported by a teacher")
    APPROVED = "approved", _("Approved")
    HIDDEN = "hidden", _("Hidden")


class AnswerQuerySet(models.QuerySet):
    def shown(self):
        """Answers the Admin has not hidden; every reader of comments goes through this."""
        return self.exclude(moderation=ModerationStatus.HIDDEN)

    def awaiting_review(self):
        """Comments the filter cleaned or a teacher reported, that no Admin has decided on."""
        return self.filter(
            models.Q(flagged=True, moderation=ModerationStatus.UNREVIEWED)
            | models.Q(moderation=ModerationStatus.REPORTED)
        )


class Answer(models.Model):
    """The answer to one question inside an anonymous response. Comment text is encrypted
    with a timeless token so the ciphertext cannot date it either."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    response = models.ForeignKey(
        FeedbackResponse,
        on_delete=models.CASCADE,
        related_name="answers",
        verbose_name=_("feedback response"),
    )
    question = models.ForeignKey(
        Question, on_delete=models.PROTECT, related_name="answers", verbose_name=_("question")
    )
    int_value = models.PositiveSmallIntegerField(_("rating"), null=True, blank=True)
    choice_value = models.CharField(_("choice"), max_length=CHOICE_VALUE_MAX_LENGTH, blank=True)
    encrypted_text = TimelessEncryptedTextField(_("comment"), null=True, blank=True)
    flagged = models.BooleanField(
        _("flagged by the filter"),
        default=False,
        help_text=_("The filter found abusive words in the comment and removed them."),
    )
    moderation = models.CharField(
        _("moderation"),
        max_length=16,
        choices=ModerationStatus.choices,
        default=ModerationStatus.UNREVIEWED,
        help_text=_("An Admin can hide a comment or approve it; the text is never edited."),
    )

    objects = AnswerQuerySet.as_manager()

    class Meta:
        verbose_name = _("answer")
        verbose_name_plural = _("answers")
        indexes = [models.Index(fields=["question", "response"], name="answer_question_response")]
        constraints = [
            models.UniqueConstraint(
                fields=["response", "question"], name="one_answer_per_question"
            ),
            models.CheckConstraint(
                condition=models.Q(int_value__isnull=True)
                | models.Q(int_value__gte=SCALE_MIN, int_value__lte=SCALE_MAX),
                name="answer_value_on_scale",
            ),
        ]

    def __str__(self):
        return f"Answer({self.pk})"


class FilterTermKind(models.TextChoices):
    BLOCK = "block", _("Blocked word")
    ALLOW = "allow", _("Allowed word")


class FilterTerm(models.Model):
    """A word the owner added to the filter's files: blocked (removed from comments) or
    allowed (never removed, even when a word list contains it). One word, stored folded."""

    term = models.CharField(_("word"), max_length=64)
    kind = models.CharField(_("kind"), max_length=8, choices=FilterTermKind.choices)

    class Meta:
        ordering = ["kind", "term"]
        verbose_name = _("filter word")
        verbose_name_plural = _("filter words")
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "term"],
                name="one_filter_term_per_kind",
                violation_error_message=_("This word is already in the list."),
            )
        ]

    def __str__(self):
        return self.term


class Draft(models.Model):
    """The unfinished form of one student, encrypted, deleted on submit."""

    student_profile = models.ForeignKey(
        "accounts.StudentProfile",
        on_delete=models.CASCADE,
        related_name="feedback_drafts",
        verbose_name=_("student"),
    )
    offering = models.ForeignKey(
        "academics.CourseOffering",
        on_delete=models.CASCADE,
        related_name="feedback_drafts",
        verbose_name=_("course offering"),
    )
    window = models.ForeignKey(
        FeedbackWindow,
        on_delete=models.CASCADE,
        related_name="drafts",
        verbose_name=_("feedback round"),
    )
    payload = EncryptedTextField(_("answers so far"))
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("draft")
        verbose_name_plural = _("drafts")
        constraints = [
            models.UniqueConstraint(
                fields=["student_profile", "offering", "window"], name="one_draft_per_round"
            )
        ]

    def __str__(self):
        return f"Draft({self.pk})"
