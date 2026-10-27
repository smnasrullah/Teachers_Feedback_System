import os
import sys

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, no_translations
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.core.services.demo import runner

PASSWORD_ENV = "DEMO_PASSWORD"  # noqa: S105 - the name of the variable, not a secret


class Command(BaseCommand):
    help = gettext_lazy(
        "Development only: create the demo accounts and demo data (safe to run again). Refuses to "
        "run unless DEBUG is on and the settings module is config.settings.dev."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete the demo data (demo_ accounts and DEMO- IDs) and stop.",
        )
        parser.add_argument(
            "--password",
            help=f"Password of the four demo accounts (else ${PASSWORD_ENV}, else a random one).",
        )

    @no_translations  # operator output stays readable on code-page consoles
    def handle(self, *args, reset, password, **options):
        for stream in (sys.stdout, sys.stderr):  # Bangla in a name must not crash a cp1252 console
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(errors="replace")
        try:
            if reset:
                removed = runner.delete_all()
                self.stdout.write(
                    self.style.SUCCESS(
                        _("Demo data removed (%(count)d accounts).") % {"count": removed}
                    )
                )
                return
            report = runner.seed(password or os.environ.get(PASSWORD_ENV) or None)
        except ValidationError as error:
            raise CommandError(" ".join(error.messages)) from error
        self._print(report)

    def _print(self, report):
        out = self.stdout.write
        out(
            self.style.SUCCESS(
                _("Demo data is ready (%(count)d new forms submitted).")
                % {"count": report.submitted}
            )
        )
        out("")
        out(_("Demo accounts (add the key to an authenticator app: time-based, 6 digits):"))
        for account in report.accounts:
            out(f"  {account.username:<14} {_('setup key')}: {account.totp_key}")
        if report.password:
            note = _("generated, shown only now") if report.password_generated else _("as given")
            out(
                _("Password (%(note)s): %(password)s") % {"note": note, "password": report.password}
            )
        else:
            out(
                _("Passwords are unchanged. Use --password or %(env)s to set them.")
                % {"env": PASSWORD_ENV}
            )
        out(_("Current code of an account: python manage.py totp_code <username>"))
        if report.spare_codes:
            out("")
            out(_("Spare sign-up pairs (student ID + activation code, shown only now):"))
            for external_id, code in report.spare_codes:
                out(f"  {external_id}   {code}")
