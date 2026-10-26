from .base import *  # noqa: F403

DEBUG = False

MIDDLEWARE.insert(  # noqa: F405
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,  # noqa: F405
    "whitenoise.middleware.WhiteNoiseMiddleware",
)

# Shared cache is mandatory: rate limits and lockouts must hold across workers.
CACHES = {"default": env.cache("CACHE_URL")}  # noqa: F405
# Django's built-in RedisCache increments atomically but is not on ratelimit's list.
SILENCED_SYSTEM_CHECKS = ["django_ratelimit.W001"]

TRUSTED_PROXY_COUNT = env.int("TRUSTED_PROXY_COUNT", default=1)  # noqa: F405
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)  # noqa: F405
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# __Host- cookies are bound to this exact host over HTTPS (no Domain, Path=/).
SESSION_COOKIE_NAME = "__Host-tfs_session"
CSRF_COOKIE_NAME = "__Host-tfs_csrf"

LOGGING = build_logging_config(  # noqa: F405
    json_logs=env.bool("LOG_JSON", default=True),  # noqa: F405
    level=env("LOG_LEVEL", default="INFO"),  # noqa: F405
)
