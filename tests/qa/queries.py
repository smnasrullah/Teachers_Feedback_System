"""Spot N+1 queries: the same statement shape run again and again within one request."""

import re
from collections import Counter

from django.db import connection
from django.test.utils import CaptureQueriesContext

_LITERALS = re.compile(r"'(?:[^']|'')*'|\b\d+\b|%s")
_LISTS = re.compile(r"\((?:\s*\?\s*,)+\s*\?\s*\)")
# Savepoints and the session/cache/axes bookkeeping repeat by design.
_IGNORED = re.compile(r"^(SAVEPOINT|RELEASE SAVEPOINT|ROLLBACK TO SAVEPOINT)")


def shape(sql: str) -> str:
    return _LISTS.sub("(?)", _LITERALS.sub("?", sql))


def repeated(sqls: list[str], threshold: int) -> dict[str, int]:
    counts = Counter(shape(sql) for sql in sqls if not _IGNORED.match(sql))
    return {statement: count for statement, count in counts.items() if count >= threshold}


def capture(client, url: str) -> tuple[int, list[str]]:
    with CaptureQueriesContext(connection) as context:
        response = client.get(url)
    return response.status_code, [query["sql"] for query in context.captured_queries]
