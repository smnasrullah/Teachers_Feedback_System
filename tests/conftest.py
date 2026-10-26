import pytest
from django.core.cache import cache

from tests import outbox


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
