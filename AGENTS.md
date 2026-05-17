# proposal-ingest — Agent Guidelines

## Project Overview

Local-first batch pipeline that scans a **read-only** proposal archive, extracts metadata via Amazon Bedrock (Claude), supports a human Q&A correction loop, and exports a clean document set + S3 manifest for RAG ingestion.

See [README.md](README.md) for setup and [docs/02_system_architecture.md](docs/02_system_architecture.md) for the core design principles.

## Build & Test

```bash
pip install -e ".[dev]"   # first-time setup

make check                # format check (black) + spell check + types (mypy) + tests (pytest) — CI gate
make lint                 # black --check on src/ and tests/
make format               # black formatter
make spellcheck           # codespell
make precommit-install    # install local git hooks
make precommit-run        # run hooks across all files
make mypy                 # mypy src/ only
pytest                    # tests only
```

After every code change, run `make check` to verify CI would pass.

## Architecture

- **Python owns all orchestration** — Bedrock is a dumb model endpoint only; no tool use, no orchestration on the model side.
- **Source root is always read-only.** All output (inventory, metadata, clean copies) goes to `--output-root`. Never write to `source_root`.
- **Two-pass AI design**: Pass 1 classifies each document; Pass 2 re-runs low-confidence docs (threshold `0.65`) using branch context. See [docs/04_processing_pipeline.md](docs/04_processing_pipeline.md).
- **Run-scoped output** — every run produces a `logs/run_YYYYMMDD_HHMMSS_<short_random>` directory with a `run_manifest.json` capturing config, git commit, and mock/real Bedrock mode.
- **Schema versioned** — `app.schema_version: "0.1.0"`. Pydantic models in `schemas.py` enforce all metadata contracts. JSON Schemas are in `schemas/`.

## Key Components

| Module | Role |
|---|---|
| `cli.py` | Typer CLI; entry point for all subcommands |
| `scanner.py` | Walks source root; year folders matched by regex `^20[0-9]{2}$`; each immediate child = one proposal branch |
| `file_filters.py` | Eligible/ineligible classification; hidden/temp/system files skipped |
| `powerpoints.py` | `.pptx`/`.pdf` same-stem supersession logic |
| `bedrock_client.py` / `mock_bedrock.py` | Real vs. deterministic-fake Bedrock calls |
| `two_pass.py` | Low-confidence flagger and pass-2 prompt runner |
| `question_loop.py` | Generates `questions_to_answer.csv`; `apply-answers` patches metadata |
| `metadata_store.py` | JSON/JSONL system of record for all AI-produced metadata |
| `clean_set_builder.py` | Sanitized flat copy of eligible documents |
| `s3_manifest.py` | JSONL manifest for S3/RAG upload |
| `tracker.py` | Parses grants tracker `.xlsx`; high-authority fields override AI guesses |
| `config.py` | Merges `config/default_config.yaml` with CLI overrides |
| `prompts.py` | Loads prompt templates from `prompts/*.md` |

## Implementation Phases

The project is built in **13 sequential phases** — never skip ahead. See [docs/10_implementation_plan.md](docs/10_implementation_plan.md) for the full phase list with acceptance criteria.

Current status: **Phases 1-11 complete** (scanner through folder synthesis). Phase 12 clean-set and S3 manifest work is next.

Build the next phase only after its acceptance criteria pass. Do not wire together modules that belong to a later phase.

## Conventions

- **CLI subcommands** use kebab-case (e.g. `run-all`, `build-clean-set`, `apply-answers`).
- **`--mock-bedrock` is a first-class flag** on every AI-touching command. Always wire it in before testing Bedrock paths.
- **Config over hardcoding** — all tunable values live in `config/default_config.yaml`. No hardcoded paths, model IDs, or thresholds in source.
- **`output_root` and `source_root` are required at runtime** — they are `null` in config by design. Missing either is a hard error.
- **Excel files**: ≤1 MB / ≤3 sheets / ≤500 non-empty cells → local extraction first; larger → direct Bedrock upload.
- **Inventory CSV has 18 fixed columns** — see `sample_outputs/file_inventory_columns.csv` for the exact schema.
- **Human review is a pipeline gate** — `stop_before_clean_set_if_critical_questions: true` prevents final output until unanswered critical questions are resolved.

## Critical Pitfalls

- **Phase 12 is still a stub** — `build-clean-set` still prints a placeholder message until the clean-set/S3 manifest phase is implemented.
- **`tracker.path` is `null` in default config** — tracker ingestion is skipped unless a tracker path is provided by CLI, environment, or config.
- **Bedrock model ID** `us.anthropic.claude-opus-4-6-v1` — use the Bedrock inference profile ID for Phase 5 smoke tests; the raw foundation model ID is rejected for on-demand Converse calls in this account.
- **OCR is disabled** (`ocr_enabled: false`) — scanned PDFs without embedded text will return empty extractions silently; this is by design for the MVP.
- **Pass-2 confidence default** — if a document returns no confidence field, the default handling (fire or skip pass 2) must be explicitly coded; it is not currently specified.

## Testing

- Tests live in `tests/`; use `--mock-bedrock` equivalents (no real AWS calls in CI).
- Sample data with no real documents: `sample_data/fake_source_root/`.
- Add a test for each new module before marking a phase complete.
- See [docs/09_testing_plan.md](docs/09_testing_plan.md) for the full test strategy.

## Docs Index

| File | Contents |
|---|---|
| [docs/01_product_requirements.md](docs/01_product_requirements.md) | Goals, non-goals, success criteria |
| [docs/02_system_architecture.md](docs/02_system_architecture.md) | Core principles, module map, data-flow diagram |
| [docs/03_metadata_schema.md](docs/03_metadata_schema.md) | Document and folder metadata field definitions |
| [docs/04_processing_pipeline.md](docs/04_processing_pipeline.md) | Per-stage I/O contracts and output file paths |
| [docs/05_cli_and_config_spec.md](docs/05_cli_and_config_spec.md) | CLI subcommand reference and config schema |
| [docs/06_aws_bedrock_setup.md](docs/06_aws_bedrock_setup.md) | AWS profile, Bedrock region, model ARN setup |
| [docs/07_human_review_workflow.md](docs/07_human_review_workflow.md) | Question loop and answer application workflow |
| [docs/09_testing_plan.md](docs/09_testing_plan.md) | Test strategy and coverage targets |
| [docs/10_implementation_plan.md](docs/10_implementation_plan.md) | **Phase-by-phase build sequence with acceptance criteria** |
