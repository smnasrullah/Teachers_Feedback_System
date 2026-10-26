.PHONY: run test lint fmt migrate seed messages css

PY ?= python

run:
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

seed:
	$(PY) manage.py seed_demo

messages:
	$(PY) scripts/compile_messages.py

css:
	$(PY) manage.py tailwind build
