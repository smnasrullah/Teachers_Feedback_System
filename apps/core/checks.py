from django.conf import settings
from django.core.checks import Error, Tags, register
from django.core.exceptions import ImproperlyConfigured

from .encryption import blind_index, encrypt

DEV_SETTINGS = "config.settings.dev"


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


@register(Tags.security)
def check_demo_second_factor(app_configs, **kwargs):
    if settings.DEMO_SKIP_SECOND_FACTOR and (
        not settings.DEBUG or settings.SETTINGS_MODULE != DEV_SETTINGS
    ):
        return [
            Error(
                "DEMO_SKIP_SECOND_FACTOR may only be on with DEBUG on and "
                f"DJANGO_SETTINGS_MODULE={DEV_SETTINGS}.",
                id="core.E004",
            )
        ]
    return []
