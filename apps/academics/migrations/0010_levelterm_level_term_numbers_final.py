"""Levels/terms become two numbers (step 3 of 3: drop the names, make the pair unique)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("academics", "0009_levelterm_level_term_numbers_data")]

    operations = [
        migrations.RemoveField(model_name="levelterm", name="name"),
        migrations.RemoveField(model_name="levelterm", name="name_bn"),
        migrations.AddConstraint(
            model_name="levelterm",
            constraint=models.UniqueConstraint(
                fields=("level", "term"),
                name="unique_level_term",
                violation_error_message="This level and term already exist.",
            ),
        ),
    ]
