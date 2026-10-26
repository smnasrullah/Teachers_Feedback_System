from django.db import models

from apps.core.encryption import EncryptedCharField, EncryptedTextField, blind_index


class Contact(models.Model):
    """Test-only model exercising encrypted fields and a blind-index unique constraint."""

    email = EncryptedCharField(max_length=254, null=True, blank=True)
    email_index = models.CharField(max_length=64, null=True, blank=True, unique=True)
    note = EncryptedTextField(blank=True)

    def __str__(self):
        return f"Contact({self.pk})"

    def save(self, *args, **kwargs):
        self.email_index = blind_index(self.email, "contact.email")
        super().save(*args, **kwargs)
