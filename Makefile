.PHONY: run test lint fmt migrate reset-db seed messages css

PY ?= python

run: migrate
	$(PY) manage.py runserver

test:
	$(PY) -m pytest -q

lint:
	ruff check .
	ruff format --check .

fmt:
	ruff check --fix .
	ruff format .

migrate:
	$(PY) manage.py migrate

reset-db:
	$(PY) scripts/reset_dev_db.py

seed:
	$(PY) manage.py seed_demo

messages:
	$(PY) scripts/compile_messages.py

css:
	$(PY) manage.py tailwind build
