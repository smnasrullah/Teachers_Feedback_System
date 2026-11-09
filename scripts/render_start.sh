#!/bin/sh
# Render's native Python runtime does not invoke docker/entrypoint.sh. This start script performs
# the same web-only checks, migrations, and optional public demo seed before starting Gunicorn.
set -eu

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.prod}"

is_enabled() {
    case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
        1|true|yes|on) return 0 ;;
        0|false|no|off|'') return 1 ;;
        *)
            printf 'Expected a boolean value (true/false or 1/0), got: %s\n' "$1" >&2
            exit 2
            ;;
    esac
}

if is_enabled "${RUN_MIGRATIONS:-1}"; then
    python manage.py check --deploy --fail-level ERROR
    python manage.py migrate --noinput
    if is_enabled "${PUBLIC_DEMO_ENABLED:-1}"; then
        python manage.py seed_demo
    fi
fi

exec gunicorn config.wsgi:application --config docker/gunicorn.conf.py
