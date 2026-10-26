"""The filter's word-list layer: what is blocked, what is allowed, and how a word is matched.

Words come from ``data/filter/{en,bn,banglish}.txt`` plus the ``FilterTerm`` rows the owner
adds in the admin. Matching is by whole word, never by substring: Bangla has no ``\\b`` and a
substring match would flag innocent words (the Scunthorpe problem), so text is cut into words
by character category and each word is compared as a unit. Common disguises are undone on a
copy used only for comparing (leetspeak, ``f*ck``, stretched letters, doubled vowels, plain
suffixes); the student's own text is cut by position, never rewritten.
"""

import re
import unicodedata
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

LEXICON_CACHE_KEY = "feedback:filter-lexicon"
LEXICON_CACHE_SECONDS = 300
LIST_FILES = ("en.txt", "bn.txt", "banglish.txt")
# Symbols people type in place of letters: "a$$", "sh!t", "f*ck", "c+nt".
OBFUSCATION = "@$*!|+"
LEET = str.maketrans(
    {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b"}
    | {"@": "a", "$": "s", "!": "i", "|": "i", "+": "t"}
)
SUFFIXES = (
    "es",
    "s",
    "ed",
    "ing",
    "er",
    "ers",
    "y",
    "ের",
    "র",
    "কে",
    "রা",
    "টা",
    "টি",
    "গুলো",
    "দের",
    "ে",
)
MIN_STEM = 3
MIN_WILDCARD_LETTERS = 2

_ELONGATED = re.compile(r"(.)\1{2,}")
_DOUBLED_VOWEL = re.compile(r"([aeiou])\1+")


def fold(text: str) -> str:
    """NFKC and case-fold, without invisible format characters, for comparing only."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return "".join(char for char in folded if unicodedata.category(char) != "Cf")


def is_word_char(char: str) -> bool:
    """Letters, combining marks (Bangla vowel signs), digits, joiners and disguise symbols."""
    category = unicodedata.category(char)
    return category[0] in "LMN" or category == "Cf" or char in OBFUSCATION


def word_spans(text: str):
    """Yield ``(start, end)`` of each maximal run of word characters."""
    start = None
    for index, char in enumerate(text):
        if is_word_char(char):
            if start is None:
                start = index
        elif start is not None:
            yield start, index
            start = None
    if start is not None:
        yield start, len(text)


@dataclass(frozen=True)
class Lexicon:
    blocked: frozenset[str]
    allowed: frozenset[str]

    def is_blocked(self, word: str) -> bool:
        """Whether ``word`` (one run of word characters) is a blocked word or a disguised one."""
        folded = fold(word)
        forms = set()
        for base in {folded, folded.translate(LEET)}:
            forms |= _variants(base)
        wildcards = {form for form in forms if "*" in form}
        stems = {stem for form in forms - wildcards for stem in _stems(form)}
        if stems & self.allowed:
            return False
        return bool(stems & self.blocked) or any(self._matches_wildcard(w) for w in wildcards)

    def _matches_wildcard(self, form: str) -> bool:
        """``f*ck``: each asterisk stands for exactly one letter of a blocked word."""
        if len(form.replace("*", "")) < MIN_WILDCARD_LETTERS:
            return False
        pattern = re.compile("".join("." if char == "*" else re.escape(char) for char in form))
        return any(pattern.fullmatch(word) for word in self.blocked if len(word) == len(form))


def _variants(form: str) -> set[str]:
    """``fuuuuck`` -> ``fuck``, ``assss`` -> ``ass``, ``fuuck`` -> ``fuck``. Only stretched runs
    (three or more) and doubled vowels collapse, so ``ball`` never becomes ``bal``."""
    forms = {form, _DOUBLED_VOWEL.sub(r"\1", form)}
    if _ELONGATED.search(form):
        forms |= {_ELONGATED.sub(r"\1\1", form), _ELONGATED.sub(r"\1", form)}
    return forms


def _stems(form: str):
    yield form
    for suffix in SUFFIXES:
        if form.endswith(suffix) and len(form) - len(suffix) >= MIN_STEM:
            yield form.removesuffix(suffix)


def parse_list(text: str) -> set[str]:
    """One word per line; blank lines and ``#`` comments are ignored."""
    return {
        fold(line.strip())
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def _build_lexicon() -> Lexicon:
    from apps.feedback.models import FilterTerm, FilterTermKind

    blocked: set[str] = set()
    for name in LIST_FILES:
        path = settings.BASE_DIR / "data" / "filter" / name
        if path.is_file():
            blocked |= parse_list(path.read_text(encoding="utf-8"))
    allowed: set[str] = set()
    for term, kind in FilterTerm.objects.values_list("term", "kind"):
        (blocked if kind == FilterTermKind.BLOCK else allowed).add(term)
    return Lexicon(frozenset(blocked), frozenset(allowed))


def get_lexicon() -> Lexicon:
    return cache.get_or_set(LEXICON_CACHE_KEY, _build_lexicon, LEXICON_CACHE_SECONDS)


def invalidate_lexicon() -> None:
    cache.delete(LEXICON_CACHE_KEY)
