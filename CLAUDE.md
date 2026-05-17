# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (from repo root, with venv activated)
pip install -e ".[dev]"

# Run all checks (lint + typecheck + tests)
make check

# Individual checks
make lint       # black --check src tests
make format     # black src tests
make ruff       # ruff check src tests
make spellcheck # codespell
make precommit-install  # install local git hooks
make precommit-run      # run hooks across all files
make mypy       # mypy src
make test       # pytest

# Apply formatter
make lint-fix   # black src tests

# Run a single test file
pytest tests/test_scanner.py

# Run a single test by name
pytest tests/test_scanner.py::test_function_name

# CLI entry point (after pip install -e)
proposal-ingest --help
```

## Architecture

This is a **local-first batch pipeline** — Python owns orchestration, state, validation, and file I/O; Claude (via Amazon Bedrock) handles classification/extraction/summarization only. Never let the model drive the workflow.

**Pipeline stages** (each is a CLI subcommand):
1. `scan` → file inventory CSV/JSONL with SHA-256 hashes and state transitions
2. `analyze` → per-document Bedrock calls producing metadata JSON (or mock mode)
3. `export-questions` / `apply-answers` → human CSV review loop
4. `build-folders` → proposal-branch metadata and Markdown summaries
5. `build-clean-set` → mirrored output directory + S3 manifest JSONL

**Config resolution order** (later wins): `config/default_config.yaml` → `.env` → CLI flags.

**Run output layout:** each run writes under `output_root/logs/run_YYYYMMDD_HHMMSS_<short_random>/`.

**Source module map** (`src/proposal_ingest/`):

| Module | Responsibility |
|---|---|
| `cli.py` | Typer entry point — all commands currently placeholder |
| `config.py` | Loads/merges YAML + env + CLI overrides |
| `scanner.py` | Year-folder / proposal-branch discovery, file inventory |
| `file_filters.py` | Eligibility rules (hidden, temp, images, ZIPs, etc.) |
| `hashing.py` | SHA-256 file hashing for dedup and stable `document_id` |
| `powerpoints.py` | `.pptx` supersession by same-stem PDF |
| `extractors.py` | Local text extraction: PDF, DOCX, XLSX, CSV, TXT |
| `bedrock_client.py` | Bedrock Runtime wrapper with retry and usage logging |
| `mock_bedrock.py` | Deterministic fake metadata for CI/offline testing |
| `schemas.py` | Pydantic v2 models for all data records |
| `metadata_store.py` | Writes JSONL/JSON to `document_metadata/` and `folder_metadata/` |
| `question_loop.py` | Generates and applies `questions_to_answer.csv` |
| `two_pass.py` | Low-confidence re-analysis with branch context |
| `folder_builder.py` | Synthesizes folder metadata and Markdown summaries |
| `clean_set_builder.py` | Copies selected docs into clean output tree |
| `s3_manifest.py` | Generates `manifests/s3_manifest.jsonl` |

**ID conventions:**
- `document_id = "doc_" + sha256(file_bytes)[0:16]` — content-stable, dedup-safe
- `proposal_id = "prop_" + slug(year + "__" + branch_name) + "__" + short_hash(relative_path)`

**File state machine** — a document transitions through states like `discovered → pending_analysis → processed_pass1 → needs_context_pass2 → processed_pass2 → included_in_clean_set`. See `docs/02_system_architecture.md` for the full list.

## Key conventions

- **Never call Bedrock in CI.** Use `--mock-bedrock` / `MOCK_BEDROCK=true` for all tests.
- **Source root is read-only.** No module ever writes to it.
- **Black line length is 100.** Use the project formatter settings from `pyproject.toml`.
- **Spell check is lightweight by design.** Prefer fixing real typos and keeping project terms in repo spell-check config over disabling whole files.
- **Mypy is lenient:** `disallow_untyped_defs = false`, `ignore_missing_imports = true` — still run it.
- Test files live in `tests/` and mirror module names (e.g., `test_scanner.py` for `scanner.py`).
- `sample_data/fake_source_root/` contains synthetic files for local testing — no real proposals.

## Implementation status

**Phases 1-5 complete** — scanner, file rules, metadata store, mock Bedrock mode, and the real Bedrock smoke test are implemented. Later document-processing and export phases remain to be built. The suggested branch order is:

1. `feature/scanner-inventory` (Phase 1–2)
2. `feature/metadata-models` (Phase 3)
3. `feature/mock-bedrock` (Phase 4)
4. `feature/bedrock-smoke-test` (Phase 5)
5. `feature/document-analysis` (Phases 6–7)
6. `feature/question-loop` (Phase 8)
7. `feature/folder-clean-output` (Phases 9–12)

See `docs/11_copilot_agent_prompts.md` for ready-to-use agent prompts per phase.

## Environment setup

Copy `.env.example` to `.env` and set:
- `PROPOSAL_INGEST_SOURCE_ROOT` — path to the read-only archive
- `PROPOSAL_INGEST_OUTPUT_ROOT` — where all output is written
- `AWS_PROFILE` — named AWS profile for Bedrock (see `docs/06_aws_bedrock_setup.md`)

Real AWS calls require Bedrock model access for the configured model (default: `claude-opus-4-6`). Always verify with `proposal-ingest bedrock-smoke-test` before a pilot run.
