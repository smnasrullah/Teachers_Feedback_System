"""Create and change questions and categories; every change is audited.

A question that has answers is frozen in its text, type and options: those answers mean
exactly that wording. Changing any of them saves a new version that ``supersedes`` the old
row and takes its place in the form; the old row stays, inactive, with its answers.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils.text import slugify
from django.utils.translation import gettext as _

from apps.auditlog.services import audit
from apps.feedback.models import CHOICE_VALUE_MAX_LENGTH, Question, QuestionCategory

LOCKED_FIELDS = ("text", "text_bn", "question_type", "options")
EDITABLE_FIELDS = ("category", "required", "applies_to")
ORDER_STEP = 10


def next_order() -> int:
    top = Question.objects.aggregate(top=Max("order"))["top"]
    return ORDER_STEP if top is None else top + ORDER_STEP


def has_answers(question: Question) -> bool:
    return question.answers.exists()


def build_options(english: list[str], bangla: list[str], existing=()) -> list[dict]:
    """Options as stored: {"value", "en", "bn"}. A value is kept when its English label
    already exists, so answers given earlier stay valid when the list is edited."""
    if bangla and len(bangla) != len(english):
        raise ValidationError(
            _("Give the same number of Bangla options as English options (or none).")
        )
    known = {
        option["en"]: option["value"]
        for option in existing
        if isinstance(option, dict) and "en" in option and "value" in option
    }
    return [
        {
            "value": known.get(label)
            or slugify(label)[:CHOICE_VALUE_MAX_LENGTH]
            or f"option-{position}",
            "en": label,
            "bn": bangla[position - 1] if bangla else "",
        }
        for position, label in enumerate(english, start=1)
    ]


def _audit(action, question, request, actor, **metadata):
    audit.record(action, request=request, actor=actor, target=question, metadata=metadata)


@transaction.atomic
def create_question(data: dict, *, actor, request=None) -> Question:
    question = Question(**{"order": next_order(), **data})
    question.full_clean()
    question.save()
    _audit("feedback.question_created", question, request, actor)
    return question


@transaction.atomic
def update_question(pk: int, data: dict, *, actor, request=None) -> Question:
    """Apply ``data`` to question ``pk``; returns the question now in force (a new version
    when answered wording changed)."""
    question = Question.objects.select_for_update().get(pk=pk)
    if hasattr(question, "superseded_by"):
        raise ValidationError(_("A newer version of this question exists. Edit that one."))
    fields = (*LOCKED_FIELDS, *EDITABLE_FIELDS)
    changed = [name for name in fields if getattr(question, name) != data[name]]
    if not changed:
        return question
    if has_answers(question) and not set(changed).isdisjoint(LOCKED_FIELDS):
        return _new_version(question, data, actor=actor, request=request)
    for name in changed:
        setattr(question, name, data[name])
    question.full_clean()
    question.save(update_fields=changed)
    _audit("feedback.question_updated", question, request, actor, changed=changed)
    return question


def _new_version(old: Question, data: dict, *, actor, request) -> Question:
    new = Question(
        **{name: data[name] for name in (*LOCKED_FIELDS, *EDITABLE_FIELDS)},
        order=old.order,
        is_active=old.is_active,
        version=old.version + 1,
    )
    new.full_clean()
    old.is_active = False
    old.save(update_fields=["is_active"])
    new.supersedes = old
    new.save()
    _audit("feedback.question_versioned", new, request, actor, replaces=old.pk, version=new.version)
    return new


@transaction.atomic
def duplicate_question(pk: int, *, actor, request=None) -> Question:
    """A fresh, inactive copy (version 1, no history) at the end of the form."""
    source = Question.objects.get(pk=pk)
    copy = Question.objects.create(
        **{name: getattr(source, name) for name in (*LOCKED_FIELDS, *EDITABLE_FIELDS)},
        order=next_order(),
        is_active=False,
    )
    _audit("feedback.question_duplicated", copy, request, actor, source=source.pk)
    return copy


@transaction.atomic
def set_active(pk: int, active: bool, *, actor, request=None) -> Question:
    question = Question.objects.select_for_update().get(pk=pk)
    if active and hasattr(question, "superseded_by"):
        raise ValidationError(
            _("This version was replaced by a newer one and cannot be activated.")
        )
    if question.is_active != active:
        question.is_active = active
        question.save(update_fields=["is_active"])
        _audit(
            f"feedback.question_{'activated' if active else 'deactivated'}",
            question,
            request,
            actor,
        )
    return question


@transaction.atomic
def reorder(positions: dict[int, int], *, actor, request=None) -> None:
    """Renumber the questions in ``positions`` ({pk: wanted position}) as 10, 20, 30..."""
    ranked = sorted(positions, key=lambda pk: (positions[pk], pk))
    questions = Question.objects.select_for_update().in_bulk(ranked)
    changed = []
    for rank, pk in enumerate((pk for pk in ranked if pk in questions), start=1):
        question = questions[pk]
        if question.order != rank * ORDER_STEP:
            question.order = rank * ORDER_STEP
            changed.append(question)
    if changed:
        Question.objects.bulk_update(changed, ["order"])
        audit.record(
            "feedback.questions_reordered",
            request=request,
            actor=actor,
            metadata={"count": len(changed)},
        )


def find_or_create_category(name: str, name_bn: str = "") -> tuple[QuestionCategory, bool]:
    """The category called ``name`` (case-insensitive), created at the end if new.

    ``name_bn`` fills a missing Bangla name but never overwrites one already set.
    """
    name, name_bn = " ".join(name.split()), " ".join(name_bn.split())
    existing = QuestionCategory.objects.filter(name__iexact=name).first()
    if existing:
        if name_bn and not existing.name_bn:
            existing.name_bn = name_bn
            existing.save(update_fields=["name_bn"])
        return existing, False
    top = QuestionCategory.objects.aggregate(top=Max("order"))["top"]
    category = QuestionCategory.objects.create(
        name=name, name_bn=name_bn, order=ORDER_STEP if top is None else top + ORDER_STEP
    )
    return category, True


@transaction.atomic
def save_category(form, *, actor, request=None) -> QuestionCategory:
    created = form.instance.pk is None
    changed = [] if created else sorted(set(form.changed_data) & set(form._meta.fields))
    if not created and not changed:
        return form.instance
    category = form.save()
    audit.record(
        f"feedback.category_{'created' if created else 'updated'}",
        request=request,
        actor=actor,
        target=category,
        metadata={"changed": changed},
    )
    return category
