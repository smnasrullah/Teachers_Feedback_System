"""The owner's additions to the filter's word lists; every change is audited."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from apps.auditlog.services import audit
from apps.feedback.models import FilterTerm
from apps.feedback.services import wordlist

MAX_TERM_LENGTH = FilterTerm._meta.get_field("term").max_length


def normalise_term(raw: str) -> str:
    """One word, folded the way the filter compares; anything else is refused."""
    term = wordlist.fold(raw.strip())
    spans = list(wordlist.word_spans(term))
    if not term or len(term) > MAX_TERM_LENGTH or spans != [(0, len(term))]:
        raise ValidationError(_("Enter a single word, without spaces."), code="not_one_word")
    return term


def add_term(term: str, kind: str, *, actor, request=None) -> FilterTerm:
    try:
        with transaction.atomic():
            record = FilterTerm.objects.create(term=term, kind=kind)
    except IntegrityError as exc:
        raise ValidationError(_("This word is already in the list."), code="duplicate") from exc
    wordlist.invalidate_lexicon()
    audit.record(
        "feedback.filter_term_added",
        request=request,
        actor=actor,
        target=record,
        metadata={"kind": kind},
    )
    return record


def remove_term(record: FilterTerm, *, actor, request=None) -> None:
    audit.record(
        "feedback.filter_term_removed",
        request=request,
        actor=actor,
        target=record,
        metadata={"kind": record.kind},
    )
    record.delete()
    wordlist.invalidate_lexicon()
