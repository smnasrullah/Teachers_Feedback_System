from django.core.management.base import BaseCommand
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.accounts.services import otp


class Command(BaseCommand):
    help = gettext_lazy(
        "Delete finished one-time code challenges, and the contacts they hold, after a day."
    )

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=1, help="Keep challenges this many days.")

    def handle(self, *args, **options):
        deleted = otp.purge_stale(older_than_days=options["days"])
        self.stdout.write(_("Deleted %(count)d one-time codes.") % {"count": deleted})
