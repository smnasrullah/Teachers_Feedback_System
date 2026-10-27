"""Levels/terms become two numbers (step 1 of 3: add the level and term columns)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("academics", "0007_semester_season_year_final")]

    operations = [
        migrations.AddField(
            model_name="levelterm",
            name="level",
            field=models.PositiveSmallIntegerField(default=1, verbose_name="level"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="levelterm",
            name="term",
            field=models.PositiveSmallIntegerField(default=1, verbose_name="term"),
            preserve_default=False,
        ),
    ]
