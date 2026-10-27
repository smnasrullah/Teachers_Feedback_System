"""Terms are stored as numbers and shown as Roman numerals (I..X), also in Bangla."""

import pytest
from django.template import Context, Template
from django.utils import translation

from apps.academics.models import LevelTerm
from apps.core.services.localize import parse_term, to_roman


def render(value) -> str:
    return Template("{% load ui %}{{ value|roman }}").render(Context({"value": value}))


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1, "I"), (4, "IV"), (9, "IX"), (10, "X"), (11, "11"), (0, "0"), (None, "")],
)
def test_filter_and_helper_agree(value, expected):
    assert render(value) == expected
    assert to_roman(value) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2", 2),
        ("ii", 2),
        (" IV ", 4),
        ("২", 2),
        ("x", 10),
        ("XI", None),
        ("", None),
        ("two", None),
    ],
)
def test_parse_term_takes_digits_and_numerals(text, expected):
    assert parse_term(text) == expected


@pytest.mark.django_db
def test_name_is_roman_in_both_languages():
    level_term = LevelTerm.objects.create(level=3, term=2, order=1)
    assert level_term.name == "Level 3 Term II"
    assert level_term.name_bn == "লেভেল ৩ টার্ম II"
    with translation.override("bn"):
        assert str(level_term) == "লেভেল ৩ টার্ম II"
    with translation.override("en"):
        assert str(level_term) == "Level 3 Term II"
