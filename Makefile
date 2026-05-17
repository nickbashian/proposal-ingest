.PHONY: install format lint lint-fix mypy test check

install:
	python -m pip install --upgrade pip
	python -m pip install -e ".[dev]"

format:
	ruff format .

lint:
	ruff check .

lint-fix:
	ruff check . --fix

mypy:
	mypy src

test:
	pytest

check: lint mypy test
