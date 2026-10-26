from django.core.management.base import BaseCommand
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.core.services.keys import rotate_encrypted_fields


class Command(BaseCommand):
    help = gettext_lazy(
        "Re-encrypt all encrypted columns with the first key in FIELD_ENCRYPTION_KEYS. "
        "Prepend the new key, run this, then remove the old key."
    )

    def handle(self, *args, **options):
        for label, count in rotate_encrypted_fields().items():
            self.stdout.write(
                _("%(label)s: %(count)d rows re-encrypted") % {"label": label, "count": count}
            )
        self.stdout.write(self.style.SUCCESS(_("Key rotation complete.")))
