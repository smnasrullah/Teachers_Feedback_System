"""Levels/terms become two numbers (step 2 of 3: fill in the level and term).

The two numbers come from the old name ("Level 2 Term 1", "লেভেল ২ টার্ম ১"): the first is the
level, the second the term. A name without two numbers becomes level ``order``, term 1. A pair
already taken is kept apart by moving the later row to the next level.
"""

import re

from django.db import migrations

ASCII_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
NUMBER = re.compile(r"\d+")
MAX_SMALL = 32767


def _pair(name: str, name_bn: str, order: int) -> tuple[int, int]:
    for text in (name, name_bn):
        numbers = [int(n) for n in NUMBER.findall(text.translate(ASCII_DIGITS))]
        if len(numbers) >= 2 and max(numbers[:2]) <= MAX_SMALL:
            return numbers[0], numbers[1]
    return order, 1


def forwards(apps, schema_editor):
    level_term_model = apps.get_model("academics", "LevelTerm")
    taken = set()
    for level_term in level_term_model.objects.order_by("order", "pk"):
        level, term = _pair(level_term.name, level_term.name_bn, level_term.order)
        while (level, term) in taken:
            level += 1
        taken.add((level, term))
        level_term.level, level_term.term = level, term
        level_term.save(update_fields=["level", "term"])


def backwards(apps, schema_editor):
    level_term_model = apps.get_model("academics", "LevelTerm")
    for level_term in level_term_model.objects.all():
        level_term.name = f"Level {level_term.level} Term {level_term.term}"
        level_term.save(update_fields=["name"])


class Migration(migrations.Migration):
    dependencies = [("academics", "0008_levelterm_level_term_numbers")]

    operations = [migrations.RunPython(forwards, backwards)]
