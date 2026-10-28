"""Semesters become Winter/Summer of a year (step 2 of 3: fill in the season and year).

Existing rows keep their dates; the season and year come from the old name ("Summer 2026",
"winter-2025", "সামার ২০২৬") or, when the name says nothing, from the start date (a start in
January to June is a Winter semester, July to December a Summer one). Two rows that would get
the same season and year are kept apart by moving the later one to the next season in turn.
"""

import re

from django.db import migrations
from django.utils import timezone

WINTER, SUMMER = "winter", "summer"
ASCII_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
YEAR = re.compile(r"(?<!\d)(\d{4})(?!\d)")
WORDS = {SUMMER: ("summer", "সামার"), WINTER: ("winter", "উইন্টার")}
LABELS = {SUMMER: "Summer", WINTER: "Winter"}
FIRST_YEAR, LAST_YEAR = 2000, 2100


def _season(name: str, start) -> str:
    folded = name.casefold()
    for season, words in WORDS.items():
        if any(word in folded for word in words):
            return season
    return WINTER if start.month <= 6 else SUMMER


def _year(name: str, start) -> int:
    match = YEAR.search(name.translate(ASCII_DIGITS))
    if match and FIRST_YEAR <= int(match.group(1)) <= LAST_YEAR:
        return int(match.group(1))
    return min(max(start.year, FIRST_YEAR), LAST_YEAR)


def _following(season: str, year: int) -> tuple[str, int]:
    return (SUMMER, year) if season == WINTER else (WINTER, year + 1)


def forwards(apps, schema_editor):
    semester_model = apps.get_model("academics", "Semester")
    taken = set()
    for semester in semester_model.objects.order_by("start_date", "pk"):
        key = (_season(semester.name, semester.start_date), _year(semester.name, semester.start_date))
        while key in taken:
            key = _following(*key)
        taken.add(key)
        semester.season, semester.year = key
        semester.save(update_fields=["season", "year"])


def backwards(apps, schema_editor):
    semester_model = apps.get_model("academics", "Semester")
    today = timezone.localdate()
    current = (
        semester_model.objects.filter(start_date__lte=today, end_date__gte=today)
        .order_by("-start_date")
        .first()
    )
    for semester in semester_model.objects.all():
        semester.name = f"{LABELS[semester.season]} {semester.year}"
        semester.is_current = current is not None and semester.pk == current.pk
        semester.save(update_fields=["name", "is_current"])


class Migration(migrations.Migration):
    dependencies = [("academics", "0005_semester_season_year")]

    operations = [migrations.RunPython(forwards, backwards)]
