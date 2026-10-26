from django.db import migrations

DEFAULTS = (
    ("Teaching", "পাঠদান"),
    ("Course Content", "কোর্সের বিষয়বস্তু"),
    ("Lab", "ল্যাব"),
    ("Assessment", "মূল্যায়ন"),
    ("Behaviour", "আচরণ"),
    ("Overall", "সামগ্রিক"),
)


def add_defaults(apps, schema_editor):
    Category = apps.get_model("feedback", "QuestionCategory")
    for position, (name, name_bn) in enumerate(DEFAULTS, start=1):
        Category.objects.get_or_create(
            name=name, defaults={"name_bn": name_bn, "order": position * 10}
        )


class Migration(migrations.Migration):
    dependencies = [("feedback", "0002_question_categories")]

    operations = [migrations.RunPython(add_defaults, migrations.RunPython.noop)]
