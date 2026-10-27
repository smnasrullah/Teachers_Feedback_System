"""Semesters become Winter/Summer of a year (step 1 of 3: the new columns, still optional)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("academics", "0004_default_grade_scale")]

    operations = [
        migrations.AddField(
            model_name="semester",
            name="season",
            field=models.CharField(
                choices=[("winter", "Winter"), ("summer", "Summer")],
                max_length=8,
                null=True,
                verbose_name="season",
            ),
        ),
        migrations.AddField(
            model_name="semester",
            name="year",
            field=models.PositiveSmallIntegerField(null=True, verbose_name="year"),
        ),
        # Not unique any more, so that undoing step 3 can bring the column back empty.
        migrations.AlterField(
            model_name="semester",
            name="name",
            field=models.CharField(blank=True, max_length=50, verbose_name="name"),
        ),
    ]
