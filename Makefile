PYTHON ?= .venv/Scripts/python.exe
PIP ?= $(PYTHON) -m pip
PYTEST_ARGS ?= --basetemp tmp/pytest-basetemp-make

.PHONY: install format lint lint-fix ruff spellcheck precommit-install precommit-run mypy test check

install:
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

format:
	$(PYTHON) -m black src tests

lint:
	$(PYTHON) -m black --check src tests

lint-fix:
	$(PYTHON) -m black src tests

ruff:
	$(PYTHON) -m ruff check src tests

spellcheck:
	$(PYTHON) -m codespell_lib

precommit-install:
	$(PYTHON) -m pre_commit install

precommit-run:
	$(PYTHON) -m pre_commit run --all-files

mypy:
	$(PYTHON) -m mypy src

test:
	$(PYTHON) -m pytest $(PYTEST_ARGS)

check: lint ruff spellcheck mypy test
