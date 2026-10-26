"""Message wording: built-in text per kind, the Admin's overrides, and safe filling-in.

Templates hold ``{name}`` placeholders. Only the names listed in ``VARIABLES`` are accepted and
nothing else is evaluated, so editable text cannot run code or reach attributes of objects.
"""

import re
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.utils import formats, timezone, translation
from django.utils.translation import gettext, ngettext
from django.utils.translation import gettext_lazy as _

from apps.notifications.models import Kind, MessageTemplate

LANGUAGES = ("en", "bn")
PLACEHOLDER = re.compile(r"\{(\w+)\}")

# What each variable stands for, shown beside the editor.
VARIABLE_HELP = {
    "round": _("the name of the feedback round"),
    "closes_at": _("when the round closes"),
    "time_left": _("how long is left, such as “1 day”"),
    "pending": _("how many forms the student still has to fill in"),
    "course": _("the course"),
    "link": _("the address of the site"),
}

VARIABLES = {
    Kind.ROUND_OPENED: ("round", "closes_at", "pending", "link"),
    Kind.CLOSING_SOON: ("round", "closes_at", "time_left", "pending", "link"),
    Kind.HOD_REMINDER: ("round", "closes_at", "course", "link"),
    Kind.RESULTS_AVAILABLE: ("round", "link"),
}


@dataclass(frozen=True)
class Wording:
    subject: str
    body: str


def _defaults(kind: str) -> Wording:
    """The built-in text in the active language (translated through the message catalogue)."""
    return {
        Kind.ROUND_OPENED: Wording(
            gettext("Feedback round open: {round}"),
            gettext(
                "The feedback round {round} is open until {closes_at}. You have {pending} "
                "form(s) to fill in. Your answers are anonymous. {link}"
            ),
        ),
        Kind.CLOSING_SOON: Wording(
            gettext("{time_left} left to give feedback"),
            gettext(
                "The feedback round {round} closes at {closes_at}, in {time_left}. You still "
                "have {pending} form(s) to fill in. Your answers are anonymous. {link}"
            ),
        ),
        Kind.HOD_REMINDER: Wording(
            gettext("Please give feedback on {course}"),
            gettext(
                "Your head of department asks you to give feedback on {course} in the round "
                "{round}, which closes at {closes_at}. Your answers are anonymous. {link}"
            ),
        ),
        Kind.RESULTS_AVAILABLE: Wording(
            gettext("Feedback results are available"),
            gettext("The results of the feedback round {round} are now available. {link}"),
        ),
    }[kind]


def default_wording(kind: str, language: str) -> Wording:
    with translation.override(language):
        return _defaults(kind)


def wording(kind: str, language: str) -> Wording:
    """The Admin's text for ``kind`` in ``language``, field by field, else the built-in text."""
    base = default_wording(kind, language)
    row = MessageTemplate.objects.filter(kind=kind).first()
    if row is None:
        return base
    return Wording(
        getattr(row, f"subject_{language}", "") or base.subject,
        getattr(row, f"body_{language}", "") or base.body,
    )


def fill(text: str, values: dict) -> str:
    return PLACEHOLDER.sub(lambda match: str(values.get(match.group(1), match.group(0))), text)


def validate_placeholders(kind: str, text: str) -> None:
    unknown = sorted(set(PLACEHOLDER.findall(text)) - set(VARIABLES[kind]))
    if unknown:
        raise ValidationError(
            _("Unknown placeholder(s): %(names)s."),
            params={"names": ", ".join("{" + name + "}" for name in unknown)},
        )


def render(kind: str, language: str, values: dict) -> Wording:
    chosen = wording(kind, language)
    return Wording(fill(chosen.subject, values), fill(chosen.body, values))


def time_left(hours: int) -> str:
    """ "3 days" for whole days of two or more, else "N hours"."""
    if hours >= 48 and hours % 24 == 0:
        return ngettext("%(n)d day", "%(n)d days", hours // 24) % {"n": hours // 24}
    return ngettext("%(n)d hour", "%(n)d hours", hours) % {"n": hours}


def local_time(moment) -> str:
    return formats.date_format(timezone.localtime(moment), "DATETIME_FORMAT")


def sample(name: str) -> str:
    """Made-up values for the Admin's test message, in the active language."""
    return {
        "round": gettext("Sample round"),
        "course": gettext("CSE101 · Programming"),
    }[name]
