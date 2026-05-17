.PHONY: install format lint lint-fix ruff spellcheck precommit-install precommit-run mypy test check

install:
	python -m pip install --upgrade pip
	python -m pip install -e ".[dev]"

format:
	black src tests

lint:
	black --check src tests

lint-fix:
	black src tests

ruff:
	ruff check src tests

spellcheck:
	codespell

precommit-install:
	pre-commit install

precommit-run:
	pre-commit run --all-files

mypy:
	mypy src

test:
	pytest

check: lint ruff spellcheck mypy test
