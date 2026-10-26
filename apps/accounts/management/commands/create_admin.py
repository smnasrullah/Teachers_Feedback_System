from getpass import getpass

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.accounts.models import User
from apps.accounts.services.passwords import validate_strong_password
from apps.auditlog.services import audit

MAX_ATTEMPTS = 3


class Command(BaseCommand):
    help = gettext_lazy(
        "Create an Admin account interactively. There is no public signup for Admins; "
        "two-factor authentication is set up at the first login."
    )

    def handle(self, *args, **options):
        email = self._ask_email()
        password = self._ask_password()
        try:
            with transaction.atomic():
                user = User.objects.create_admin(password, contact_email=email)
                audit.record("admin.created", target=user, metadata={"via": "create_admin"})
        except IntegrityError:
            raise CommandError(_("That e-mail address is already in use.")) from None
        self.stdout.write(self.style.SUCCESS(_("Admin account created.")))
        self.stdout.write(_("Username: %(username)s") % {"username": user.username})
        self.stdout.write(_("Sign in, then set up two-factor authentication when asked."))

    def _ask_email(self) -> str:
        for _attempt in range(MAX_ATTEMPTS):
            email = input(_("Contact e-mail: ")).strip()
            try:
                validate_email(email)
            except ValidationError:
                self.stderr.write(_("Enter a valid e-mail address."))
                continue
            return email
        raise CommandError(_("Too many invalid attempts."))

    def _ask_password(self) -> str:
        for _attempt in range(MAX_ATTEMPTS):
            password = getpass(_("Password: "))
            try:
                validate_strong_password(password)
            except ValidationError as error:
                for message in error.messages:
                    self.stderr.write(message)
                continue
            if getpass(_("Password (again): ")) != password:
                self.stderr.write(_("The passwords do not match."))
                continue
            return password
        raise CommandError(_("Too many invalid attempts."))
