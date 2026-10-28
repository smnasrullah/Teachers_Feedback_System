# Deploying on Render

This project is a Django application. Its production image is defined by the root
`Dockerfile`; use Render's **Docker** runtime so the build also installs the native libraries
required for Bengali PDF reports. The repository's `pyproject.toml` only configures Ruff,
pytest, and coverage. Python dependencies are pinned in `requirements/base.txt` and
`requirements/prod.txt`; Poetry is not the package manager for this project.

## Web service

Connect the GitHub repository and configure the Render service as follows:

| Setting | Value |
| --- | --- |
| Runtime | Docker |
| Dockerfile Path | `./Dockerfile` |
| Docker Context | `.` (repository root) |
| Build Command | Not applicable; Render builds the Dockerfile |
| Docker Command / Start Command | Leave blank; the image runs its existing entrypoint and Gunicorn command |
| Health Check Path | `/healthz` |

Render's `PORT` is used by Gunicorn. Do not replace the image command with Django's development
server. Set the environment variables below on the web service. Use the existing Render
PostgreSQL/Key Value resources if the app already has production data; do not provision a new
database and point the live app at it accidentally.

## Required environment variables

Set secrets in the Render dashboard, never in Git:

| Variable | Value |
| --- | --- |
| `DJANGO_SETTINGS_MODULE` | `config.settings.prod` |
| `DJANGO_READ_ENV_FILE` | `false` |
| `DJANGO_SECRET_KEY` | A unique random value of at least 50 characters |
| `FIELD_ENCRYPTION_KEYS` | A valid Fernet key; preserve the existing production key when migrating an existing database |
| `BLIND_INDEX_KEY` | A unique random value of at least 32 characters; preserve the existing production key when migrating existing data |
| `DATABASE_URL` | The internal URL for the existing Render PostgreSQL database |
| `CACHE_URL` | The internal Redis URL for the Render Key Value instance |
| `CELERY_BROKER_URL` | Redis URL, e.g. the Key Value URL with `/0` appended |
| `CELERY_RESULT_BACKEND` | Redis URL, e.g. the same Key Value URL with `/1` appended |
| `DJANGO_ALLOWED_HOSTS` | Render hostname, without scheme, e.g. `your-service.onrender.com` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | HTTPS origin, e.g. `https://your-service.onrender.com` |
| `SITE_URL` | HTTPS site URL, e.g. `https://your-service.onrender.com` |
| `RUN_MIGRATIONS` | `1` (the existing container entrypoint runs deploy checks and migrations before Gunicorn) |
| `PORT` | `10000` (Render's default; Gunicorn binds to this value) |

Generate new secrets with the commands documented in `.env.production.example`. Do not
regenerate encryption or blind-index keys for an existing database: losing or changing them
can make encrypted data unreadable or break identifier lookups. Configure the same database,
Redis, and key values on any worker services.

For a custom domain, include its hostname in `DJANGO_ALLOWED_HOSTS`, and its HTTPS origin in
`DJANGO_CSRF_TRUSTED_ORIGINS`; set `SITE_URL` to the canonical public URL.

## Background tasks, e-mail, and uploads

The production Compose setup runs Celery worker and beat processes separately. To keep scheduled
reminders and other asynchronous work active on Render, create two Docker background workers
from the same repository and Dockerfile, with the same database, Redis, and secret environment
variables:

- Worker command: `celery -A config worker --loglevel=info`
- Beat command: `celery -A config beat --loglevel=info --schedule=/tmp/celerybeat-schedule`

Do not set `RUN_MIGRATIONS=1` on those workers. Configure the `EMAIL_*` variables in
`.env.production.example` if e-mail notifications are required.

Render's filesystem is ephemeral by default. If users upload avatars or teacher photos, attach
a persistent disk to the web service at `/app/media` (and keep one web instance), or configure
durable object storage before relying on those uploads. The application uses PostgreSQL in
production; local SQLite files are not a Render production database.
