from .base import *  # noqa: F403
from .hardening import require_production_settings

DEBUG = False

# Every secret and address comes from the environment, with no fallback (missing = refuse).
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")  # noqa: F405
DATABASES = {"default": env.db("DATABASE_URL")}  # noqa: F405
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)  # noqa: F405
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
# Shared cache is mandatory: rate limits and lockouts must hold across workers.
CACHES = {"default": env.cache("CACHE_URL")}  # noqa: F405
CELERY_BROKER_URL = env("CELERY_BROKER_URL")  # noqa: F405
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND")  # noqa: F405
SITE_URL = env("SITE_URL").rstrip("/")  # noqa: F405

require_production_settings(
    secret_key=SECRET_KEY,  # noqa: F405
    fernet_keys=FIELD_ENCRYPTION_KEYS,  # noqa: F405
    blind_index_key=BLIND_INDEX_KEY,  # noqa: F405
    database_url=env("DATABASE_URL"),  # noqa: F405
    redis_urls={
        "CACHE_URL": env("CACHE_URL"),  # noqa: F405
        "CELERY_BROKER_URL": CELERY_BROKER_URL,
        "CELERY_RESULT_BACKEND": CELERY_RESULT_BACKEND,
    },
    allowed_hosts=ALLOWED_HOSTS,
    csrf_origins=CSRF_TRUSTED_ORIGINS,  # noqa: F405
    site_url=SITE_URL,
)

MIDDLEWARE.insert(  # noqa: F405
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,  # noqa: F405
    "whitenoise.middleware.WhiteNoiseMiddleware",
)

SILENCED_SYSTEM_CHECKS = [
    # Django's built-in RedisCache increments atomically but is not on ratelimit's list.
    "django_ratelimit.W001",
    # HSTS preload is deliberately off: preload lists are hard to leave if the domain changes.
    "security.W021",
]

# Caddy (docker-compose.prod.yml) is the one proxy: it terminates TLS and sets these headers.
TRUSTED_PROXY_COUNT = env.int("TRUSTED_PROXY_COUNT", default=1)  # noqa: F405
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# __Host- cookies are bound to this exact host over HTTPS (no Domain, Path=/).
SESSION_COOKIE_NAME = "__Host-tfs_session"
CSRF_COOKIE_NAME = "__Host-tfs_csrf"

# Development features stay off whatever the environment says (core.E004 also guards the first).
DEMO_SKIP_SECOND_FACTOR = False
DEMO_PASSWORD = ""

LOGGING = build_logging_config(  # noqa: F405
    json_logs=env.bool("LOG_JSON", default=True),  # noqa: F405
    level=env("LOG_LEVEL", default="INFO"),  # noqa: F405
)
