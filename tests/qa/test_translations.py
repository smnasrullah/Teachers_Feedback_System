"""Every translatable string in code and templates has a Bangla entry (no GNU gettext needed)."""

import ast
import re
from pathlib import Path

import polib
from django.conf import settings
from django.utils.translation.template import templatize

ROOT = Path(settings.BASE_DIR)
GETTEXT_NAMES = {
    "_",
    "gettext",
    "gettext_lazy",
    "gettext_noop",
    "ngettext",
    "ngettext_lazy",
    "pgettext",
    "pgettext_lazy",
    "npgettext",
    "npgettext_lazy",
}
TEMPLATE_CALL = re.compile(r"\b(?:np|n|p)?gettext\(")


def _literal(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal(node.left), _literal(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _messages(tree):
    """(context, msgid) of every gettext call with a literal message."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name not in GETTEXT_NAMES:
            continue
        args = node.args
        context = None
        if name.startswith(("pgettext", "npgettext")):
            context, args = _literal(args[0]), args[1:]
        message = _literal(args[0]) if args else None
        if message is not None:
            yield context, message


def _template_calls(source):
    """The gettext(...) calls templatize() emits, each parsed on its own."""
    for match in TEMPLATE_CALL.finditer(source):
        for end in range(match.end(), len(source) + 1):
            if source[end - 1] != ")":
                continue
            try:
                yield ast.parse(source[match.start() : end], mode="eval")
            except SyntaxError:
                continue
            break


def _python_sources():
    for folder in ("apps", "config"):
        for path in (ROOT / folder).rglob("*.py"):
            if "migrations" not in path.parts:
                yield path, ast.parse(path.read_text(encoding="utf-8"))


def _template_sources():
    for path in (ROOT / "templates").rglob("*"):
        if path.suffix in {".html", ".txt"}:
            source = templatize(path.read_text(encoding="utf-8"), origin=str(path))
            for tree in _template_calls(source):
                yield path, tree


def test_every_message_has_a_bangla_translation():
    catalogue = polib.pofile(str(ROOT / "locale/bn/LC_MESSAGES/django.po"), encoding="utf-8")
    translated = {(entry.msgctxt, entry.msgid) for entry in catalogue.translated_entries()}
    missing = sorted(
        f"{path.relative_to(ROOT)}: {message!r}"
        for sources in (_python_sources(), _template_sources())
        for path, tree in sources
        for context, message in _messages(tree)
        if (context, message) not in translated
    )

    assert not missing, "\n".join(missing)


def test_catalogue_has_no_fuzzy_or_untranslated_entries():
    catalogue = polib.pofile(str(ROOT / "locale/bn/LC_MESSAGES/django.po"), encoding="utf-8")

    assert not catalogue.fuzzy_entries()
    assert not catalogue.untranslated_entries()
