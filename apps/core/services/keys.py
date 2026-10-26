from django.apps import apps
from django.db import transaction

from apps.core.encryption import EncryptedFieldMixin


def encrypted_models():
    """Yield ``(model, [field names])`` for every concrete model with encrypted columns."""
    for model in apps.get_models():
        meta = model._meta
        if meta.proxy or not meta.managed:
            continue
        names = [f.attname for f in meta.concrete_fields if isinstance(f, EncryptedFieldMixin)]
        if names:
            yield model, names


def rotate_encrypted_fields(batch_size: int = 500) -> dict[str, int]:
    """Re-encrypt every encrypted column under the primary key.

    Reading decrypts with any configured key; ``update()`` writes with the first key.
    Returns rows rewritten per model label.
    """
    rewritten: dict[str, int] = {}
    for model, names in encrypted_models():
        manager = model._base_manager
        count = 0
        with transaction.atomic():
            rows = manager.order_by("pk").values_list("pk", *names)
            for pk, *values in rows.iterator(chunk_size=batch_size):
                manager.filter(pk=pk).update(**dict(zip(names, values, strict=True)))
                count += 1
        rewritten[model._meta.label] = count
    return rewritten
