from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.accounts.models import User
from apps.accounts.services import twofactor

DEV_SETTINGS = "config.settings.dev"


class Command(BaseCommand):
    help = gettext_lazy(
        "Development only: print the current authenticator code of an account. Refuses to run "
        "unless DEBUG is on and the settings module is config.settings.dev."
    )

    def add_arguments(self, parser):
        parser.add_argument("username")

    def handle(self, *args, **options):
        if not settings.DEBUG or settings.SETTINGS_MODULE != DEV_SETTINGS:
            raise CommandError(
                _("totp_code only runs with DEBUG on and DJANGO_SETTINGS_MODULE=%(module)s.")
                % {"module": DEV_SETTINGS}
            )
        user = User.objects.filter(username=options["username"].strip().lower()).first()
        if user is None or not user.totp_secret:
            raise CommandError(_("No account with an authenticator has that username."))
        self.stdout.write(twofactor.current_code(user.totp_secret))
