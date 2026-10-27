"""Gunicorn settings for the web container (docker-compose.prod.yml)."""

import os

# Only Caddy reaches this port: the web container publishes nothing to the host.
bind = "0.0.0.0:8000"
workers = int(os.environ.get("GUNICORN_WORKERS", "3"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))
# Recycle workers now and then so slow memory growth (PDF exports) cannot build up.
max_requests = 1000
max_requests_jitter = 100
# No access log: request lines with times could be matched against feedback submissions.
accesslog = None
errorlog = "-"
