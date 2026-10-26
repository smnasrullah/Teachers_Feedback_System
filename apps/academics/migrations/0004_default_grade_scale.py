"""Seed the 4.00 grade scale (UGC Bangladesh uniform grading); the admin can edit it."""

from decimal import Decimal

from django.db import migrations

DEFAULT_SCALE = (
    ("A+", "4.00", True),
    ("A", "3.75", True),
    ("A-", "3.50", True),
    ("B+", "3.25", True),
    ("B", "3.00", True),
    ("B-", "2.75", True),
    ("C+", "2.50", True),
    ("C", "2.25", True),
    ("D", "2.00", True),
    ("F", "0.00", False),
)


def seed(apps, schema_editor):
    grade_scale = apps.get_model("academics", "GradeScale")
    for letter, points, is_pass in DEFAULT_SCALE:
        grade_scale.objects.get_or_create(
            letter=letter, defaults={"points": Decimal(points), "is_pass": is_pass}
        )


class Migration(migrations.Migration):
    dependencies = [("academics", "0003_results_promotion")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
