"""Write and verify the audit trail.

``record()`` is the only way rows are created. It appends to a SHA-256 chain: each row
stores the previous row's hash, and ``prev_hash`` is unique so the chain cannot fork.
"""

import hmac
import json
import re
from dataclasses import dataclass
from enum import StrEnum

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.auditlog.models import GENESIS_HASH, AuditEvent
from apps.core.logging import scrub_text
from apps.core.net import UNKNOWN_IP, client_ip
from apps.core.permissions import primary_role

ACTION_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
MAX_METADATA_STRING = 200
MAX_USER_AGENT = 512
MAX_ATTEMPTS = 5

# Metadata keys that could carry a secret or feedback content are refused outright.
FORBIDDEN_KEY_PARTS = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "otp",
        "totp",
        "token",
        "secret",
        "comment",
        "comments",
        "answer",
        "answers",
        "feedback",
        "text",
    }
)
FORBIDDEN_KEYS = frozenset({"code", "activation_code", "recovery_code", "reset_code"})


def _clean_metadata(value, path="metadata"):
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path}: keys must be strings.")
            lowered = key.lower()
            if lowered in FORBIDDEN_KEYS or not FORBIDDEN_KEY_PARTS.isdisjoint(
                lowered.replace("-", "_").split("_")
            ):
                raise ValueError(f"{path}.{key}: secrets and feedback text are not audited.")
            cleaned[key] = _clean_metadata(item, f"{path}.{key}")
        return cleaned
    if isinstance(value, list | tuple):
        return [_clean_metadata(item, f"{path}[]") for item in value]
    if isinstance(value, str):
        if len(value) > MAX_METADATA_STRING:
            raise ValueError(f"{path}: free text is not audited ({len(value)} chars).")
        return scrub_text(value)
    if value is None or isinstance(value, bool | int | float):
        return value
    raise ValueError(f"{path}: unsupported type {type(value).__name__}.")


def _request_fields(request) -> dict:
    if request is None:
        return {"ip": None, "user_agent": "", "request_id": ""}
    ip = client_ip(request)
    # Normalise exactly as the column will store it so the hash survives a round trip.
    ip_field = AuditEvent._meta.get_field("ip")
    return {
        "ip": None if ip == UNKNOWN_IP else ip_field.to_python(ip),
        "user_agent": request.META.get("HTTP_USER_AGENT", "")[:MAX_USER_AGENT],
        "request_id": getattr(request, "request_id", ""),
    }


def record(
    action: str,
    *,
    request=None,
    actor=None,
    target=None,
    department_id: int | None = None,
    metadata: dict | None = None,
) -> AuditEvent:
    """Append one audit event.

    ``action`` is a dotted lowercase name such as ``"auth.login_failed"``. ``actor``
    defaults to the signed-in user of ``request``; ``target`` is the model instance acted
    on. ``metadata`` must be small JSON without secrets or free text.
    """
    if not ACTION_PATTERN.fullmatch(action):
        raise ValueError(f"Invalid audit action name: {action!r}")
    user = getattr(request, "user", None)
    if actor is None and user is not None and user.is_authenticated:
        actor = user
    clean = json.loads(json.dumps(_clean_metadata(metadata or {}), allow_nan=False))
    fields = {
        "actor_id": actor.pk if actor is not None else None,
        "actor_username": actor.get_username() if actor is not None else "",
        "actor_role": primary_role(actor),
        "action": action,
        "object_type": target._meta.label_lower if target is not None else "",
        "object_id": str(target.pk) if target is not None else "",
        "department_id": department_id,
        "metadata": clean,
        **_request_fields(request),
    }
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _append(fields)
        except IntegrityError:
            # Another writer appended first (unique prev_hash); re-read the tail and retry.
            if attempt == MAX_ATTEMPTS:
                raise


def _append(fields: dict) -> AuditEvent:
    with transaction.atomic():
        last = AuditEvent.objects.select_for_update().order_by("-id").only("hash").first()
        event = AuditEvent(
            created_at=timezone.now(),
            prev_hash=last.hash if last else GENESIS_HASH,
            **fields,
        )
        event.hash = event.compute_hash()
        event.save(force_insert=True)
        return event


class ChainFault(StrEnum):
    LINK = "link"
    CONTENT = "content"


@dataclass(frozen=True)
class ChainReport:
    checked: int
    broken_at: int | None = None
    fault: ChainFault | None = None

    @property
    def ok(self) -> bool:
        return self.broken_at is None


def verify_chain(batch_size: int = 2000) -> ChainReport:
    """Walk every row in id order, re-hashing it and checking the link to its predecessor."""
    expected_prev = GENESIS_HASH
    checked = 0
    for event in AuditEvent.objects.order_by("id").iterator(chunk_size=batch_size):
        if not hmac.compare_digest(event.prev_hash, expected_prev):
            return ChainReport(checked, event.pk, ChainFault.LINK)
        if not hmac.compare_digest(event.hash, event.compute_hash()):
            return ChainReport(checked, event.pk, ChainFault.CONTENT)
        expected_prev = event.hash
        checked += 1
    return ChainReport(checked)
