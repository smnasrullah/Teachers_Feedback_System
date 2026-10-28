"""Container healthcheck: exit 0 when the app's /healthz answers 200 (database and cache up).

It calls gunicorn directly, so it sends what Caddy would: the site's host name and the
forwarded HTTPS scheme (otherwise Django would refuse the host or redirect to HTTPS).
"""

import os
import sys
import urllib.error
import urllib.request

host = os.environ["DJANGO_ALLOWED_HOSTS"].split(",")[0].strip()
request = urllib.request.Request(
    "http://127.0.0.1:8000/healthz", headers={"Host": host, "X-Forwarded-Proto": "https"}
)
try:
    with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
        sys.exit(0 if response.status == 200 else 1)
except (urllib.error.URLError, OSError):
    sys.exit(1)
