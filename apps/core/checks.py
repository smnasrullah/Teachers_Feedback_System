from django.conf import settings
from django.core.checks import Error, Tags, register
from django.core.exceptions import ImproperlyConfigured

from .encryption import blind_index, encrypt

DEV_SETTINGS = "config.settings.dev"
DEMO_SETTINGS = "config.settings.demo"
PROD_SETTINGS = "config.settings.prod"


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
    safe_dev = settings.DEBUG and settings.SETTINGS_MODULE == DEV_SETTINGS
    safe_demo = (
        not settings.DEBUG
        and settings.IS_DEMO_SITE
        and (
            (settings.SETTINGS_MODULE == DEMO_SETTINGS and settings.DEMO_DATABASE_ISOLATED)
            or (settings.SETTINGS_MODULE == PROD_SETTINGS and settings.PUBLIC_DEMO_ENABLED)
        )
    )
    if settings.DEMO_SKIP_SECOND_FACTOR and not (safe_dev or safe_demo):
        return [
            Error(
                "DEMO_SKIP_SECOND_FACTOR is allowed only in local development, an isolated demo "
                "deployment, or production with PUBLIC_DEMO_ENABLED.",
                id="core.E004",
            )
        ]
    return []
