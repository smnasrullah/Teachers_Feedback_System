from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, no_translations
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.feedback.services import question_bank


class Command(BaseCommand):
    help = gettext_lazy("Load the question bank from a markdown file (safe to run again).")

    def add_arguments(self, parser):
        parser.add_argument("path", type=Path, help="e.g. docs/QUESTION_BANK.md")

    @no_translations  # operator output stays readable on code-page consoles
    def handle(self, *args, path, **options):
        try:
            report = question_bank.load_file(path)
        except OSError as error:
            raise CommandError(
                _("Cannot read %(path)s: %(error)s") % {"path": path, "error": error}
            ) from error
        self.stdout.write(
            self.style.SUCCESS(
                _(
                    "Questions: %(created)d created, %(updated)d updated, %(unchanged)d unchanged; "
                    "%(categories)d new categories; %(placeholders)d placeholders."
                )
                % {
                    "created": report.created,
                    "updated": report.updated,
                    "unchanged": report.unchanged,
                    "categories": report.categories,
                    "placeholders": report.placeholders,
                }
            )
        )
        for skipped in report.skipped:
            self.stderr.write(
                _("Skipped line %(line)d: %(reason)s")
                % {"line": skipped.line, "reason": skipped.reason}
            )
