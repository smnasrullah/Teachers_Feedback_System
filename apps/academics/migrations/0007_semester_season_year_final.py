"""Semesters become Winter/Summer of a year (step 3 of 3: required, unique, old columns gone)."""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("academics", "0006_semester_season_year_data")]

    operations = [
        migrations.RemoveConstraint(model_name="semester", name="one_current_semester"),
        migrations.RemoveField(model_name="semester", name="is_current"),
        migrations.RemoveField(model_name="semester", name="name"),
        migrations.AlterField(
            model_name="semester",
            name="season",
            field=models.CharField(
                choices=[("winter", "Winter"), ("summer", "Summer")],
                max_length=8,
                verbose_name="season",
            ),
        ),
        migrations.AlterField(
            model_name="semester",
            name="year",
            field=models.PositiveSmallIntegerField(
                validators=[MinValueValidator(2000), MaxValueValidator(2100)],
                verbose_name="year",
            ),
        ),
        migrations.AlterField(
            model_name="semester",
            name="end_date",
            field=models.DateField(
                help_text="The last day of the semester; promotion can start after it.",
                verbose_name="end date",
            ),
        ),
        migrations.AddConstraint(
            model_name="semester",
            constraint=models.UniqueConstraint(
                fields=("season", "year"),
                name="semester_unique_season_year",
                violation_error_message="This semester already exists.",
            ),
        ),
    ]
