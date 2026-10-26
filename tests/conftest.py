import pytest
from django.core.cache import cache
from django.db import connection

from tests import outbox

POSTGRES_ONLY = pytest.mark.skip(
    reason=(
        "needs PostgreSQL (set DATABASE_URL=postgres://...): SQLite ignores select_for_update "
        "and serialises every writer, so a parallel test proves nothing there"
    )
)


def pytest_collection_modifyitems(config, items):
    if connection.vendor == "postgresql":
        return
    for item in items:
        if item.get_closest_marker("postgres"):
            item.add_marker(POSTGRES_ONLY)


@pytest.fixture(autouse=True)
def _isolated_state():
    """Rate limits live in the cache and delivered codes in memory: start every test clean."""
    cache.clear()
    outbox.sent.clear()
    yield
    cache.clear()


@pytest.fixture
def sent():
    """Messages delivered through the test OTP backend, oldest first."""
    return outbox.sent


@pytest.fixture
def web(client):
    """A test client that asks for English (the site default is Bangla)."""
    client.defaults["HTTP_ACCEPT_LANGUAGE"] = "en"
    return client
