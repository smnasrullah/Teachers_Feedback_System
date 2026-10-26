"""The answer filter every comment passes before it is stored (BLUEPRINT §1, §5.2 A8).

``clean()`` is the single entry point ``submit_feedback`` calls. Layers, in order:

a. normalise: NFC, invisible characters dropped;
c. personal details removed: e-mails, links, Bangladeshi phone numbers, ID-like digit runs;
b. abusive words removed (or masked) by whole-word match against the word lists;
e. optional AI check on what is left (fails open);
d. junk check: nothing meaningful left, or only symbols, digits or keyboard mashing.

Text that needed nothing stays exactly as written. ``preview_clean()`` runs the local layers
only, so a form can pre-check a comment without calling an outside service.
"""

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from django.utils.translation import gettext_lazy as _

from apps.core.services import system_settings
from apps.feedback.services import wordlist
from apps.feedback.services.moderation import get_backend

MASK_CHAR = "*"
MIN_LETTER_RATIO = 0.4
MASH_MIN_LENGTH = 4
MASH_MAX_LENGTH = 40
MASH_RUN = 4
MASH_RUN_SHARE = 0.6
MASH_FEW_DISTINCT = 2
MASH_FEW_DISTINCT_MIN_LENGTH = 6
KEYBOARD_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")
KEYBOARD_RUNS = frozenset(
    row[start:end]
    for row in (*KEYBOARD_ROWS, *(row[::-1] for row in KEYBOARD_ROWS))
    for start in range(len(row))
    for end in range(start + MASH_RUN, len(row) + 1)
)
_INVISIBLE = dict.fromkeys(map(ord, "​⁠﻿­᠎"))

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(
    r"(?:\b(?:https?|ftp)://|\bwww\.)\S+"
    r"|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|edu|gov|info|xyz|bd|io|me)\b(?:/\S*)?",
    re.IGNORECASE,
)
# 01712345678, +880 1712-345678, 017 1234 5678 (Bangla digits too: \d is Unicode-aware).
_PHONE = re.compile(r"(?<!\d)(?:\+?88[\s-]?)?(?:0[\s-]?)?1[3-9](?:[\s-]?\d){8}(?!\d)")
# Six or more digits in a row, or nine or more with hyphens or slashes (student IDs).
_ID_LIKE = re.compile(r"(?<!\d)(?:\d{6,}|\d(?:[-/]?\d){8,})(?!\d)")
_PERSONAL = (_EMAIL, _URL, _PHONE, _ID_LIKE)
_SPACES = re.compile(r"[^\S\n]{2,}")
_SPACE_BEFORE_PUNCTUATION = re.compile(r"[^\S\n]+([,.;:!?।])")


class Reason(StrEnum):
    EMPTY = "empty"
    PROFANITY = "profanity"
    PERSONAL_INFO = "personal_info"
    GIBBERISH = "gibberish"


REASON_MESSAGES = {
    Reason.EMPTY: _("The answer is empty."),
    Reason.PROFANITY: _("Abusive words are not allowed."),
    Reason.PERSONAL_INFO: _(
        "Phone numbers, e-mail addresses, links and ID numbers are removed from answers."
    ),
    Reason.GIBBERISH: _("The answer looks like random characters or has no words."),
}


@dataclass(frozen=True)
class CleanResult:
    text: str
    removed_count: int = 0
    flagged: bool = False
    reasons: tuple[Reason, ...] = ()

    @property
    def empty(self) -> bool:
        """Nothing meaningful is left to store."""
        return not self.text.strip()

    def messages(self) -> list[str]:
        """The reasons in the reader's language, for telling the student why to rewrite."""
        return [str(REASON_MESSAGES[reason]) for reason in self.reasons]


def clean(text: str) -> CleanResult:
    """Filter ``text`` with every layer, the AI check included when it is switched on."""
    return _run(text, ai=True)


def preview_clean(text: str) -> CleanResult:
    """Filter ``text`` with the local layers only (no outside call); nothing is stored."""
    return _run(text, ai=False)


def _run(text: str, *, ai: bool) -> CleanResult:
    text = unicodedata.normalize("NFC", text).translate(_INVISIBLE)
    if not text.strip():
        return CleanResult("", reasons=(Reason.EMPTY,))
    text, personal = _remove_personal_details(text)
    text, abusive = _remove_abusive_words(text, wordlist.get_lexicon())
    if ai and text.strip():
        text, found = _remove_ai_terms(text)
        abusive += found
    removed = personal + abusive
    if removed:
        text = _tidy(text)
    reasons = [
        reason
        for reason, count in ((Reason.PERSONAL_INFO, personal), (Reason.PROFANITY, abusive))
        if count
    ]
    if text.strip() and _is_junk(text):
        text = ""
        if not removed:
            reasons.append(Reason.GIBBERISH)
    return CleanResult(text, removed, flagged=abusive > 0, reasons=tuple(reasons))


def _remove_personal_details(text: str) -> tuple[str, int]:
    removed = 0
    for pattern in _PERSONAL:
        text, count = pattern.subn("", text)
        removed += count
    return text, removed


def _remove_abusive_words(text: str, lexicon: wordlist.Lexicon) -> tuple[str, int]:
    spans = []
    for start, end in wordlist.word_spans(text):
        word = text[start:end]
        if lexicon.is_blocked(word):
            spans.append((start, end))
            continue
        core = word.strip(wordlist.OBFUSCATION)
        if core != word and core and lexicon.is_blocked(core):
            start += len(word) - len(word.lstrip(wordlist.OBFUSCATION))
            spans.append((start, start + len(core)))
    return _cut(text, spans), len(spans)


def _remove_ai_terms(text: str) -> tuple[str, int]:
    """Cut the words the AI backend names; a term that is not whole words of the text is
    ignored, so an invented answer cannot change a comment."""
    spans = []
    for term in get_backend().abusive_terms(text):
        for found in re.finditer(re.escape(term), text, re.IGNORECASE):
            before = text[found.start() - 1] if found.start() else " "
            after = text[found.end()] if found.end() < len(text) else " "
            if not (wordlist.is_word_char(before) or wordlist.is_word_char(after)):
                spans.append(found.span())
    spans = _merge(spans)
    return _cut(text, spans), len(spans)


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _cut(text: str, spans: list[tuple[int, int]]) -> str:
    """Remove (or, with ``PROFANITY_ACTION=mask``, star out) each span, last first."""
    mask = system_settings.get("PROFANITY_ACTION") == "mask"
    for start, end in reversed(spans):
        text = text[:start] + (MASK_CHAR * (end - start) if mask else "") + text[end:]
    return text


def _tidy(text: str) -> str:
    """Close the gaps a removal left, only when something was removed."""
    return _SPACE_BEFORE_PUNCTUATION.sub(r"\1", _SPACES.sub(" ", text)).strip()


def _is_junk(text: str) -> bool:
    """No letters, mostly symbols or digits, or only keyboard mashing."""
    shown = [char for char in text if not char.isspace()]
    letters = sum(unicodedata.category(char)[0] in "LM" for char in shown)
    if letters / len(shown) < MIN_LETTER_RATIO:
        return True
    words = [
        wordlist.fold(text[start:end].strip(wordlist.OBFUSCATION))
        for start, end in wordlist.word_spans(text)
    ]
    words = [word for word in words if word.isalpha()]
    return bool(words) and all(_is_mash(word) for word in words)


def _is_mash(word: str) -> bool:
    if len(word) < MASH_MIN_LENGTH or not word.isascii():
        return False
    if len(word) > MASH_MAX_LENGTH:
        return True
    long_enough = len(word) >= MASH_FEW_DISTINCT_MIN_LENGTH
    if long_enough and (len(set(word)) <= MASH_FEW_DISTINCT or set(word).isdisjoint("aeiouy")):
        return True
    return _longest_keyboard_run(word) / len(word) >= MASH_RUN_SHARE


def _longest_keyboard_run(word: str) -> int:
    longest = 0
    for start in range(len(word)):
        for end in range(start + MASH_RUN, len(word) + 1):
            if word[start:end] in KEYBOARD_RUNS:
                longest = max(longest, end - start)
    return longest
