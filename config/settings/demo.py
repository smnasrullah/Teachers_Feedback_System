"""Production-hardening settings for an isolated, public demo deployment.

The site exposes shared demo credentials and includes a demo administrator. It must use a
dedicated PostgreSQL database with sample data only; never point it at the live institution DB.
"""

from django.core.exceptions import ImproperlyConfigured

from .prod import *  # noqa: F403

DEMO_DATABASE_ISOLATED = env.bool("DEMO_DATABASE_ISOLATED", default=False)  # noqa: F405
if not DEMO_DATABASE_ISOLATED:
    raise ImproperlyConfigured(
        "Demo deployment refused: set DEMO_DATABASE_ISOLATED=true only for a dedicated "
        "sample-data database. Never point this service at the live database."
    )

DEMO_PASSWORD = env("DEMO_PASSWORD")  # noqa: F405
if len(DEMO_PASSWORD) < 12:
    raise ImproperlyConfigured("DEMO_PASSWORD must contain at least 12 characters.")

IS_DEMO_SITE = True
DEMO_SKIP_SECOND_FACTOR = True

# A single demo web service can process its sample notifications without a separate worker.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
