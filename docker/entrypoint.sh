#!/bin/sh
# Container entrypoint (Linux, inside the image). Only the web service sets RUN_MIGRATIONS=1,
# so exactly one process migrates; worker and beat start after web reports healthy.
set -eu

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    python manage.py check --deploy --fail-level ERROR
    python manage.py migrate --noinput
    # Seed public demo accounts after migrations on the web service. A worker with
    # RUN_MIGRATIONS=0 never seeds on startup. Disable the demo with PUBLIC_DEMO_ENABLED=0.
    if [ "${PUBLIC_DEMO_ENABLED:-1}" = "1" ]; then
        python manage.py seed_demo
    fi
fi

exec "$@"
