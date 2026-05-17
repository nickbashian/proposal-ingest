# 08 — Repo and Development Tooling

## Python target

Target Python version:

```text
Python 3.13
```

Practical note: if an AWS SDK or document extraction dependency causes avoidable setup friction, fall back to Python 3.12. The code should avoid relying on 3.13-only features unless needed.

## Environment management

Use either:

- conda environment, or
- `venv + pip`

Example venv setup:

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

## Core dependencies

Suggested:

```text
boto3
botocore
pydantic
python-dotenv
pyyaml
pandas
openpyxl
pypdf
python-docx
click or typer
rich
```

Recommended CLI framework: `typer`, because it is concise and friendly for typed CLIs.

## Dev dependencies

```text
ruff
pytest
mypy
types-PyYAML
pandas-stubs
```

## Formatting and linting

Use Ruff for linting and formatting.

Commands:

```bash
ruff check .
ruff format .
```

## Type checking

Use mypy, but start with pragmatic settings.

```bash
mypy src
```

## Tests

Use pytest.

```bash
pytest
```

## Makefile targets

```makefile
install:
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
```

## GitHub Actions

CI should run:

- install package
- Ruff check
- Ruff format check
- mypy
- pytest

Do not run real Bedrock calls in CI.

## Git hygiene

Never commit:

- `.env`
- source proposal files
- processed output
- raw model responses
- logs
- confidential metadata
- tracker workbook

## Sample data

Include fake sample documents only.

Suggested sample tree:

```text
sample_data/fake_source_root/
  2025/
    2025 Fake DOE SBIR Battery Project/
      Technical Volume FINAL.docx
      Budget.xlsx
      FOA Instructions.pdf
      Quad Chart.pdf
      Quad Chart.pptx
      Support Letter.docx
  General/
    Empower Grant Activities/
      Grants In Progress/
        fake_grants_tracker.xlsx
```

The fake data should be synthetic and safe to commit.

## Recommended branch strategy

For this prototype:

- `main`: stable working prototype
- feature branches for major modules

Suggested order:

1. `feature/scanner-inventory`
2. `feature/metadata-models`
3. `feature/mock-bedrock`
4. `feature/bedrock-smoke-test`
5. `feature/document-analysis`
6. `feature/question-loop`
7. `feature/folder-clean-output`

## Minimal README sections for repo

- What the tool does
- What it does not do
- Setup
- AWS setup
- First mock run
- First Bedrock smoke test
- Process one file
- Process one folder
- Full pipeline
- Output structure
- Safety/confidentiality notes
