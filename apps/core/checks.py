from django.conf import settings
from django.core.checks import Error, Tags, register
from django.core.exceptions import ImproperlyConfigured

from .encryption import blind_index, encrypt


@register(Tags.security)
def check_encryption_keys(app_configs, **kwargs):
    errors = []
    try:
        encrypt("check")
    except ImproperlyConfigured as exc:
        errors.append(Error(str(exc), id="core.E001"))
    try:
        blind_index("check", "check")
    except ImproperlyConfigured as exc:
        errors.append(Error(str(exc), id="core.E002"))
    blind_key = settings.BLIND_INDEX_KEY
    if blind_key and (
        blind_key in settings.FIELD_ENCRYPTION_KEYS or blind_key == settings.SECRET_KEY
    ):
        errors.append(
            Error(
                "BLIND_INDEX_KEY must be separate from FIELD_ENCRYPTION_KEYS and SECRET_KEY.",
                id="core.E003",
            )
        )
    return errors
