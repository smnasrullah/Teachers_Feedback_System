import hashlib
import json
from datetime import UTC

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

GENESIS_HASH = "0" * 64

# Every column except ``id`` and ``hash`` itself; the id is assigned by the database
# after the hash is computed, and deletions are still caught by the prev_hash links.
HASHED_FIELDS = (
    "created_at",
    "actor_id",
    "actor_username",
    "actor_role",
    "action",
    "object_type",
    "object_id",
    "department_id",
    "ip",
    "user_agent",
    "request_id",
    "metadata",
    "prev_hash",
)


class AuditLogImmutableError(Exception):
    """Audit rows are append-only; they are never updated or deleted."""


class AuditEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AuditLogImmutableError("Audit events cannot be updated.")

    def delete(self):
        raise AuditLogImmutableError("Audit events cannot be deleted.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise AuditLogImmutableError("Audit events cannot be updated.")

    def bulk_create(self, objs, *args, **kwargs):
        raise AuditLogImmutableError("Write audit events one at a time with audit.record().")


class AuditEvent(models.Model):
    """Append-only, hash-chained record of a security-relevant action.

    No foreign keys: rows must outlive the users and objects they mention, and a
    cascade or SET_NULL would need an UPDATE/DELETE that the database refuses.
    Never holds secrets or feedback text (enforced in ``services.audit``).
    """

    created_at = models.DateTimeField(_("date"), default=timezone.now, db_index=True)
    actor_id = models.BigIntegerField(_("actor id"), null=True, blank=True, db_index=True)
    actor_username = models.CharField(_("actor"), max_length=150, blank=True)
    actor_role = models.CharField(_("role"), max_length=16, blank=True)
    action = models.CharField(_("action"), max_length=64, db_index=True)
    object_type = models.CharField(_("object type"), max_length=100, blank=True)
    object_id = models.CharField(_("object id"), max_length=64, blank=True)
    department_id = models.BigIntegerField(_("department id"), null=True, blank=True, db_index=True)
    ip = models.GenericIPAddressField(_("IP address"), null=True, blank=True)
    user_agent = models.CharField(_("user agent"), max_length=512, blank=True)
    request_id = models.CharField(_("request id"), max_length=64, blank=True)
    metadata = models.JSONField(_("details"), default=dict, blank=True)
    prev_hash = models.CharField(_("previous hash"), max_length=64, unique=True)
    hash = models.CharField(_("hash"), max_length=64, unique=True)

    objects = AuditEventQuerySet.as_manager()

    class Meta:
        ordering = ("id",)
        verbose_name = _("audit event")
        verbose_name_plural = _("audit events")

    def __str__(self):
        return f"{self.action} #{self.pk}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AuditLogImmutableError("Audit events cannot be updated.")
        if self.hash != self.compute_hash():
            raise AuditLogImmutableError("Write audit events with audit.record().")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AuditLogImmutableError("Audit events cannot be deleted.")

    def compute_hash(self) -> str:
        payload = {name: getattr(self, name) for name in HASHED_FIELDS}
        payload["created_at"] = self.created_at.astimezone(UTC).isoformat()
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()
