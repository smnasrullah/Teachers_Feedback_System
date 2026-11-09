#!/bin/sh
# Render's native Python runtime does not invoke docker/entrypoint.sh. This start script performs
# the same web-only checks, migrations, and optional public demo seed before starting Gunicorn.
set -eu

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.prod}"

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    python manage.py check --deploy --fail-level ERROR
    python manage.py migrate --noinput
    if [ "${PUBLIC_DEMO_ENABLED:-1}" = "1" ]; then
        python manage.py seed_demo
    fi
fi

exec gunicorn config.wsgi:application --config docker/gunicorn.conf.py
