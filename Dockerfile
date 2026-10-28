# Production image (docker-compose.prod.yml). Stage 1 installs the Python packages and builds
# the CSS and static files; stage 2 keeps only what runs, as a non-root user.

FROM python:3.12-slim AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH=/opt/venv/bin:$PATH

RUN python -m venv /opt/venv
WORKDIR /app

COPY requirements/base.txt requirements/prod.txt requirements/
RUN pip install -r requirements/prod.txt

COPY . .

# Production settings refuse to load without strong secrets, so this step makes throwaway ones
# that live only inside this RUN (nothing is connected to; the values are not kept in the image).
RUN set -eu; \
    export DJANGO_SETTINGS_MODULE=config.settings.prod; \
    export DJANGO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(64))')"; \
    export FIELD_ENCRYPTION_KEYS="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"; \
    export BLIND_INDEX_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"; \
    export DATABASE_URL="postgres://build:$(python -c 'import secrets; print(secrets.token_hex(16))')@localhost:5432/build"; \
    export CACHE_URL=redis://localhost:6379/2 CELERY_BROKER_URL=redis://localhost:6379/0 \
        CELERY_RESULT_BACKEND=redis://localhost:6379/1 \
        DJANGO_ALLOWED_HOSTS=localhost SITE_URL=https://localhost; \
    python manage.py tailwind build; \
    python manage.py collectstatic --noinput; \
    rm -rf .django_tailwind_cli


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    DJANGO_READ_ENV_FILE=false \
    MEDIA_ROOT=/app/media

# WeasyPrint (PDF reports) needs Pango and HarfBuzz. PDFs embed the fonts in static/fonts/pdf;
# Noto (with Bengali) is only the fallback for glyphs those lack.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 \
        shared-mime-info fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 tfs
WORKDIR /app

COPY --from=build /opt/venv /opt/venv
# Code stays owned by root (read-only for the app); only uploads are writable.
COPY --from=build /app /app
RUN mkdir -p /app/media && chown tfs:tfs /app/media && chmod 0755 docker/entrypoint.sh

USER tfs
EXPOSE 8000
ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--config", "docker/gunicorn.conf.py"]
