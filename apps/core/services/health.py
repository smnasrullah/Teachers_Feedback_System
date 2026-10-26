import logging
import secrets

from django.core.cache import cache
from django.db import connection

logger = logging.getLogger(__name__)


def check_health() -> bool:
    """Return True when both the database and the cache respond."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        token = secrets.token_hex(8)
        cache.set("healthz", token, timeout=10)
        return cache.get("healthz") == token
    except Exception:
        logger.exception("Health check failed")
        return False
