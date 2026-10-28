#!/bin/sh
# Container entrypoint (Linux, inside the image). Only the web service sets RUN_MIGRATIONS=1,
# so exactly one process migrates; worker and beat start after web reports healthy.
set -eu

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    python manage.py check --deploy --fail-level ERROR
    python manage.py migrate --noinput
fi

exec "$@"
