"""Read a rendered page the way a person does: visible text and the labels assistive tech reads."""

import re
from functools import cache
from html.parser import HTMLParser
from pathlib import Path

import polib
from django.conf import settings

INVALID = "INVALID-TEMPLATE-VARIABLE"
SPOKEN_ATTRIBUTES = ("aria-label", "title", "placeholder", "alt")
LEAKS = re.compile(r"\bNone\b|\{\{|\{%|Traceback|" + INVALID)


class _Reader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.segments: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "template"}:
            self.skip += 1
        for name, value in attrs:
            if name in SPOKEN_ATTRIBUTES and value:
                self.segments.append(value)

    def handle_endtag(self, tag):
        if tag in {"script", "style", "template"} and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.segments.append(data)


def segments(html: str) -> list[str]:
    """Visible text nodes and spoken attributes, whitespace collapsed, empties dropped."""
    reader = _Reader()
    reader.feed(html)
    return [text for text in (" ".join(part.split()) for part in reader.segments) if text]


@cache
def english_messages() -> frozenset[str]:
    """English source strings that have a different Bangla translation."""
    path = Path(settings.BASE_DIR) / "locale/bn/LC_MESSAGES/django.po"
    catalogue = polib.pofile(str(path), encoding="utf-8")
    return frozenset(
        " ".join(entry.msgid.split())
        for entry in catalogue.translated_entries()
        if entry.msgstr != entry.msgid and "%" not in entry.msgid and "{" not in entry.msgid
    )


def leaks(html: str) -> list[str]:
    """Raw template syntax, invalid variables, tracebacks or a literal None shown to people."""
    return [text for text in segments(html) if LEAKS.search(text)]


def untranslated(html: str) -> list[str]:
    """Text on a Bangla page that is exactly an English catalogue string."""
    english = english_messages()
    return [text for text in segments(html) if text in english]
