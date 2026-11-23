import os

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction

from apps.accounts.models import EMAIL_INDEX_PURPOSE, User
from apps.accounts.services.passwords import validate_strong_password
from apps.auditlog.services import audit
from apps.core.encryption import blind_index
from apps.core.permissions import Role


class Command(BaseCommand):
    help = "Create or update the real Admin from environment variables during deployment."

    def handle(self, *args, **options):
        username = os.environ.get("REAL_ADMIN_USERNAME", "").strip().lower()
        email = os.environ.get("REAL_ADMIN_EMAIL", "").strip()
        password = os.environ.get("REAL_ADMIN_PASSWORD", "")

        if not username or not email or not password:
            raise CommandError(
                "Set REAL_ADMIN_USERNAME, REAL_ADMIN_EMAIL, and REAL_ADMIN_PASSWORD."
            )

        try:
            validate_email(email)
            validate_strong_password(password)
        except ValidationError as error:
            raise CommandError(" ".join(error.messages)) from error

        email_index = blind_index(email, EMAIL_INDEX_PURPOSE)

        with transaction.atomic():
            user = User.objects.select_for_update().filter(username=username).first()
            if user is None:
                email_owner = User.objects.filter(contact_email_index=email_index).first()
                if email_owner is not None:
                    raise CommandError("REAL_ADMIN_EMAIL belongs to another account.")
                user = User.objects.create_admin(
                    password,
                    username=username,
                    contact_email=email,
                )
                audit.record("admin.created", target=user, metadata={"via": "bootstrap_admin"})
                created = True
            else:
                if user.role != Role.ADMIN:
                    raise CommandError("REAL_ADMIN_USERNAME belongs to a non-Admin account.")
                email_owner = (
                    User.objects.filter(contact_email_index=email_index).exclude(pk=user.pk).first()
                )
                if email_owner is not None:
                    raise CommandError("REAL_ADMIN_EMAIL belongs to another account.")
                user.set_password(password)
                user.contact_email = email
                user.save(update_fields=["password", "contact_email"])
                audit.record(
                    "admin.password_reset",
                    target=user,
                    metadata={"via": "bootstrap_admin"},
                )
                created = False

        action = "created" if created else "password updated"
        self.stdout.write(f"Real Admin {action}: {username}")
