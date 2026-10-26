from django.core.management.base import BaseCommand, CommandError
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.auditlog.services.audit import ChainFault, verify_chain


class Command(BaseCommand):
    help = gettext_lazy("Verify that the audit log hash chain is intact.")

    def handle(self, *args, **options):
        report = verify_chain()
        if report.ok:
            message = _("Audit chain intact: %(count)d events verified.") % {
                "count": report.checked
            }
            self.stdout.write(self.style.SUCCESS(message))
            return
        reasons = {
            ChainFault.LINK: _(
                "it does not link to the previous event (missing or reordered rows)"
            ),
            ChainFault.CONTENT: _("its content does not match its hash (row was altered)"),
        }
        raise CommandError(
            _("Audit chain broken at event %(id)d: %(reason)s. %(count)d earlier events intact.")
            % {"id": report.broken_at, "reason": reasons[report.fault], "count": report.checked}
        )
