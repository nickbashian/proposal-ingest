ifeq ($(OS),Windows_NT)
PYTHON ?= .venv/Scripts/python.exe
BOOTSTRAP_PYTHON ?= py -3.13
else
PYTHON ?= .venv/bin/python
BOOTSTRAP_PYTHON ?= python3.13
endif

PIP ?= $(PYTHON) -m pip
PYTEST_ARGS ?= --basetemp tmp/pytest-basetemp-make

.PHONY: install install-browser diagnose config-check format lint lint-fix ruff spellcheck secrets \
	precommit-install precommit-run mypy test browser-smoke mock-run db-up db-smoke db-down \
	db-reset check

install:
	$(BOOTSTRAP_PYTHON) scripts/dev.py bootstrap --with-browser

install-browser:
	$(PYTHON) scripts/dev.py install-browser

diagnose:
	$(PYTHON) scripts/dev.py diagnose

config-check:
	$(PYTHON) scripts/dev.py config-check

format:
	$(PYTHON) -m black src tests scripts

lint:
	$(PYTHON) -m black --check src tests scripts

lint-fix:
	$(PYTHON) -m black src tests scripts

ruff:
	$(PYTHON) -m ruff check src tests scripts

spellcheck:
	$(PYTHON) -m codespell_lib

secrets:
	$(PYTHON) scripts/scan_secrets.py

precommit-install:
	$(PYTHON) -m pre_commit install

precommit-run:
	$(PYTHON) -m pre_commit run --all-files

mypy:
	$(PYTHON) -m mypy src scripts

test:
	$(PYTHON) -c "from pathlib import Path; Path('tmp').mkdir(parents=True, exist_ok=True)"
	$(PYTHON) -m pytest $(PYTEST_ARGS)

browser-smoke:
	$(PYTHON) scripts/dev.py browser-smoke

mock-run:
	$(PYTHON) scripts/dev.py mock-run

db-up:
	$(PYTHON) scripts/dev.py db-up

db-smoke:
	$(PYTHON) scripts/dev.py db-smoke

db-down:
	$(PYTHON) scripts/dev.py db-down

db-reset:
	$(PYTHON) scripts/dev.py db-reset

check: lint ruff spellcheck mypy secrets config-check test browser-smoke
