import sys

from django.core.management.base import BaseCommand, CommandError, no_translations
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.core.services import visibility


class Command(BaseCommand):
    help = gettext_lazy(
        "Operator check: why a student or teacher sees (or does not see) their courses and "
        "rounds. Prints no passwords, codes, secrets or feedback."
    )

    def add_arguments(self, parser):
        parser.add_argument("--registry-id", required=True, help="The student or teacher ID.")

    @no_translations  # operator output stays readable on code-page consoles
    def handle(self, *args, registry_id, **options):
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(errors="replace")
        reports = visibility.explain(registry_id)
        if not reports:
            raise CommandError(_("No registry entry has this ID."))
        for checks in reports:
            for check in checks:
                mark = self.style.SUCCESS("[ok]") if check.ok else self.style.WARNING("[!!]")
                self.stdout.write(f"{mark} {check.label}: {check.detail}")
            self.stdout.write("")
