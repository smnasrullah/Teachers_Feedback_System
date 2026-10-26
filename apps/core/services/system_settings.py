"""Settings the Admin can change while the site runs (``SystemSetting``).

Every key has a default in Django settings (so an environment variable still sets the first
value), limits that are checked here and nowhere else, and a label for the settings page. The
stored overrides are cached as one dict; saving clears it. A change is audited with the old and
the new value, and nothing here holds feedback text or secrets.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.auditlog.services import audit
from apps.core.models import SystemSetting

CACHE_KEY = "system_settings:overrides"
CACHE_SECONDS = 300

# Below this many responses a single answer can be traced back by elimination.
MIN_RESPONSES_FLOOR = 3
MIN_RESPONSES_CEILING = 100
MAX_REMINDERS = 5
MAX_REMINDER_HOURS = 24 * 30


class Kind(StrEnum):
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    CHOICE = "choice"
    HOURS = "hours"


@dataclass(frozen=True)
class Definition:
    key: str
    kind: Kind
    label: object
    help: object = ""
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple = field(default_factory=tuple)

    def normalise(self, raw):
        """The stored form of ``raw``, or ``ValidationError``."""
        return _NORMALISERS[self.kind](self, raw)


def _within(definition, value) -> None:
    if definition.minimum is not None and value < definition.minimum:
        raise ValidationError(
            _("%(label)s cannot be below %(minimum)s."),
            params={"label": definition.label, "minimum": definition.minimum},
        )
    if definition.maximum is not None and value > definition.maximum:
        raise ValidationError(
            _("%(label)s cannot be above %(maximum)s."),
            params={"label": definition.label, "maximum": definition.maximum},
        )


def _int(definition, raw) -> int:
    if isinstance(raw, bool):
        raise ValidationError(_("Enter a whole number."))
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ValidationError(_("Enter a whole number.")) from None
    _within(definition, value)
    return value


def _float(definition, raw) -> float:
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        raise ValidationError(_("Enter a number.")) from None
    if not math.isfinite(value):
        raise ValidationError(_("Enter a number."))
    _within(definition, value)
    return round(value, 1)


def _bool(definition, raw) -> bool:
    if isinstance(raw, bool):
        return raw
    raise ValidationError(_("Choose yes or no."))


def _choice(definition, raw) -> str:
    if raw in {value for value, _label in definition.choices}:
        return raw
    raise ValidationError(_("Choose one of the listed options."))


def _hours(definition, raw) -> list[int]:
    items = raw.replace(";", ",").split(",") if isinstance(raw, str) else list(raw)
    hours = {_int(definition, item) for item in items if str(item).strip()}
    if len(hours) > MAX_REMINDERS:
        raise ValidationError(
            _("Use at most %(count)s reminders."), params={"count": MAX_REMINDERS}
        )
    return sorted(hours, reverse=True)


_NORMALISERS: dict[Kind, Callable] = {
    Kind.INT: _int,
    Kind.FLOAT: _float,
    Kind.BOOL: _bool,
    Kind.CHOICE: _choice,
    Kind.HOURS: _hours,
}

DEFINITIONS = {
    definition.key: definition
    for definition in (
        Definition(
            "MIN_RESPONSES",
            Kind.INT,
            _("Minimum responses"),
            _(
                "Results and comments stay hidden below this many responses. "
                "It can never be lower than 3."
            ),
            minimum=MIN_RESPONSES_FLOOR,
            maximum=MIN_RESPONSES_CEILING,
        ),
        Definition(
            "LOW_RATING_THRESHOLD",
            Kind.FLOAT,
            _("Low rating alert"),
            _("A course average below this raises an alert for the head of department."),
            minimum=1,
            maximum=5,
        ),
        Definition(
            "SHOW_OWN_ID_TO_STUDENT",
            Kind.BOOL,
            _("Show students their own ID"),
            _("Off: a student never sees their student ID on their own pages."),
        ),
        Definition(
            "PROFANITY_ACTION",
            Kind.CHOICE,
            _("Abusive words in comments"),
            _("What the comment filter does with them."),
            choices=(("remove", _("Remove them")), ("mask", _("Replace them with asterisks"))),
        ),
        Definition(
            "RESULTS_VISIBLE",
            Kind.CHOICE,
            _("Results for teachers and heads"),
            _("Results are never shown before a round closes; holding them delays that further."),
            choices=(
                ("after_close", _("Show once the round has closed")),
                ("held", _("Hold back for now")),
            ),
        ),
        Definition(
            "DRAFT_RETENTION_DAYS",
            Kind.INT,
            _("Keep unfinished drafts for (days)"),
            _("Drafts are deleted this long after the last save."),
            minimum=1,
            maximum=365,
        ),
        Definition(
            "REMINDER_HOURS_BEFORE_CLOSE",
            Kind.HOURS,
            _("Reminder schedule (hours before a round closes)"),
            _("Comma-separated, for example 48, 24. Leave empty for no automatic reminders."),
            minimum=1,
            maximum=MAX_REMINDER_HOURS,
        ),
    )
}


def _overrides() -> dict:
    stored = cache.get(CACHE_KEY)
    if stored is None:
        stored = dict(SystemSetting.objects.values_list("key", "value"))
        cache.set(CACHE_KEY, stored, CACHE_SECONDS)
    return stored


def get(key: str):
    """The Admin's value for ``key``, else the default from Django settings."""
    if key not in DEFINITIONS:
        raise KeyError(key)
    overrides = _overrides()
    return overrides[key] if key in overrides else getattr(settings, key)


def current() -> dict:
    return {key: get(key) for key in DEFINITIONS}


def update(changes: dict, *, actor, request=None) -> list[str]:
    """Validate and store ``changes`` (key -> raw value); returns the keys that changed.

    Nothing is stored unless every value is valid. Each changed key is one audit event with
    its old and new value.
    """
    errors = {}
    clean = {}
    for key, raw in changes.items():
        try:
            clean[key] = DEFINITIONS[key].normalise(raw)
        except ValidationError as error:
            errors[key] = error
    if errors:
        raise ValidationError(errors)
    changed = []
    with transaction.atomic():
        before = current()
        for key, value in clean.items():
            if value == before[key]:
                continue
            SystemSetting.objects.update_or_create(key=key, defaults={"value": value})
            audit.record(
                "settings.changed",
                request=request,
                actor=actor,
                metadata={"setting": key, "old": before[key], "new": value},
            )
            changed.append(key)
    cache.delete(CACHE_KEY)
    return changed
