FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 \
        libffi-dev shared-mime-info fonts-noto-core fonts-hind-siliguri curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 tfs
WORKDIR /app

COPY requirements/ requirements/
RUN pip install -r requirements/prod.txt

COPY --chown=tfs:tfs . .

USER tfs
RUN DJANGO_SECRET_KEY=build-only python manage.py tailwind build \
    && DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
