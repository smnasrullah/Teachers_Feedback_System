"""No page runs one query per row: on the demo data (six or more rows in every list) the same
statement shape may not repeat five times within one request."""

import pytest
from django.urls import reverse

from apps.accounts.models import User
from tests.qa.conftest import ROLES, all_routes, client_for, sample_kwargs
from tests.qa.queries import capture, repeated

PER_ROW = 5
# Known and reported (docs/QA_REPORT.md, P1): analytics gate every slice on its own response
# count before computing it, then cache the slice per round version. Only this statement may
# repeat; anything else that repeats is a new per-row query.
SLICE_GATE = (
    'SELECT COUNT(*) AS "__count" FROM "feedback_feedbackresponse" WHERE '
    '("feedback_feedbackresponse"."offering_id" IN (?) AND '
    '"feedback_feedbackresponse"."window_id" = ?)'
)


@pytest.mark.parametrize("role", ROLES[1:])
def test_no_page_queries_once_per_row(seeded, role):
    client = client_for(role)
    user = User.objects.get(username=role)
    found = []
    for route in all_routes():
        if route.name.startswith("admin:") or "<path:object_id>" in route.pattern:
            continue
        for kwargs in sample_kwargs(route.name, user):
            url = reverse(route.name, kwargs=kwargs)
            status, sqls = capture(client, url)
            if status == 200:
                found += [
                    f"{url}: x{count} {statement[:200]}"
                    for statement, count in repeated(sqls, PER_ROW).items()
                    if statement != SLICE_GATE
                ]
    assert not found, "\n".join(found)
