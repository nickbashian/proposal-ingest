# proposal-ingest

The September 2026 product build follows [the MVP implementation playbook](docs/mvp/README.md):
11 sequential PRs covering this development baseline, a private drafting application, live
integrations, and bounded 2025 expansion. MVP numbering is separate from the historical CLI phases.

Local-first document ingestion and metadata pipeline for a historical grant/proposal archive.

## What this tool does

- Scans a read-only local folder tree and builds a complete file inventory.
- Filters, hashes, and deduplicates files; handles PowerPoint/PDF supersession.
- Sends supported documents to Amazon Bedrock (Claude) for metadata extraction and classification.
- Synthesizes canonical, cross-document proposal-level metadata records.
- Arbitrates proposal-level unresolved decisions into a small, budget-capped set of human review questions.
- Supports a human question-and-answer correction loop via CSV, applying answers to the correct scope (document, document family, or proposal).
- Performs a two-pass contextual review for low-confidence documents.
- Synthesizes proposal-branch folder metadata and Markdown summaries.
- Exports a clean mirrored document set ready for future S3 upload and RAG ingestion.

## What this tool does NOT do

- It never modifies source files (read-only).
- It does not perform OCR (out of scope for MVP).
- It does not upload anything to S3 (it generates a manifest only).
- It does not process PowerPoints directly by default (they are inventoried; PDFs take priority).
- It does not run without explicit configuration (no defaults assume a particular machine).
- It does not commit `.env`, source documents, processed output, logs, or raw model responses.

## Repository structure

```
proposal-ingest/
  pyproject.toml            Python project definition and dependency groups
  requirements-dev.lock     Fully pinned Python 3.13 development environment
  Makefile                  Developer shortcuts (install, lint, test, check)
  compose.dev.yml           Disposable loopback-only PostgreSQL development service
  .env.example              Environment variable template (copy to .env)
  .gitignore                Excludes confidential data, environments, build artifacts
  .github/workflows/ci.yml  GitHub Actions CI (Black, Ruff, spell check, mypy, pytest — no real Bedrock)
  config/
    default_config.yaml     Default runtime configuration
    document_type_rules.yaml  File type inclusion/exclusion rules
    knowledge_base_policies.yaml  Standing policies used by proposal-level synthesis
  prompts/                  Bedrock prompt templates
  schemas/                  JSON Schema definitions for metadata records
  src/proposal_ingest/      Python package source
  tests/                    pytest test suite
  sample_data/              Documented synthetic proposal files (no real data)
  sample_outputs/           Reference output column layouts and example JSONL
  docs/                     Full specification documents
```

## Setup

### Requirements and diagnosis

- Python 3.13 (3.12 is not supported by the package contract)
- Git and GNU Make
- Docker Desktop/Engine with the Compose plugin for the disposable PostgreSQL service
- AWS CLI only for explicitly requested live Bedrock work; it is not needed for setup or mock runs

Keep the checkout and Python environment outside OneDrive. No Node dependency is currently used. If
a later phase adds one, install it beneath the user's `.codex` root rather than this checkout.

Diagnose before installing or reconnecting tools:

```powershell
# Windows
py -3.13 scripts/dev.py diagnose
```

```bash
# Linux
python3.13 scripts/dev.py diagnose
```

The report distinguishes missing executables, an inactive Docker service, and missing GitHub/AWS/
CodeRabbit sign-in. Live AWS identity and local Chromium launch are opt-in via `--check-auth` and
`--check-browser`.

### Install

```powershell
# Windows (install GNU Make once if diagnose reports it missing)
winget install --exact --id ezwinports.make --scope user

git clone https://github.com/nickbashian/proposal-ingest.git
cd proposal-ingest
py -3.13 scripts/dev.py bootstrap --with-browser
make db-up
make check
make mock-run
```

Open a new terminal after the WinGet installation if `make` is not immediately on `PATH`.

```bash
# Ubuntu/Linux; install Python 3.13, GNU Make, and Docker using supported OS packages first.
git clone https://github.com/nickbashian/proposal-ingest.git
cd proposal-ingest
python3.13 scripts/dev.py bootstrap --with-browser
make db-up
make check
make mock-run
```

Bootstrap creates `.venv`, installs `requirements-dev.lock`, installs the package editable without
re-resolving dependencies, and places Chromium under `~/.codex/proposal-ingest/playwright` by
default. It refuses a checkout under OneDrive. The existing mock pipeline uses only synthetic data,
requires no AWS credentials, and writes under `tmp/mvp00-mock`.

### Configure

Copy `.env.example` to `.env` and fill in your local paths:

```powershell
Copy-Item .env.example .env
```

```bash
cp .env.example .env
```

**Critical `.env` fields:**

| Variable | Purpose |
|---|---|
| `PROPOSAL_INGEST_SOURCE_ROOT` | Path to the read-only proposal archive folder |
| `PROPOSAL_INGEST_OUTPUT_ROOT` | Path where all output will be written |
| `PROPOSAL_INGEST_TRACKER_PATH` | Path to the grants tracker workbook (optional) |
| `AWS_PROFILE` | AWS named profile for Bedrock calls |

### Verify dev tooling

```bash
# Black, Ruff, spelling, mypy, secrets/private-artifact scan, pytest, local Chromium
make check
```

Install the local git hook once per clone:

```bash
make precommit-install
```

Or individually:

```bash
make format  # black src tests
make lint    # black --check src tests
make ruff    # ruff check src tests
make spellcheck  # codespell
make secrets  # likely credentials and forbidden private artifact paths
make precommit-run  # pre-commit run --all-files
make mypy    # mypy src scripts
make test    # pytest
make browser-smoke  # local page only; no network
```

Disposable database commands are `make db-up`, `make db-smoke`, `make db-down`, and the explicit
destructive development-only cleanup `make db-reset`. PostgreSQL is required for application tests.
Run `make app-migrate`, `make fixture-slice`, and `make app-run` to start the local product slice;
run `make worker` in another terminal. Enable local sign-in explicitly in the process environment.
See the [MVP-02 operator guide](docs/mvp/implementation/MVP-02-OPERATIONS.md) for the complete
collection → review → publication → evidence → writing demo, and the
[MVP-01 operator guide](docs/mvp/implementation/MVP-01-OPERATIONS.md) for worker recovery,
production configuration, and backup/restore. Application settings use process environment; the
historical CLI's `.env` loading remains separate. `make fixture-job` remains available for the
smaller MVP-01 durable-job demonstration.

VS Code workspace settings recommend the Code Spell Checker extension and keep spelling
diagnostics at hint level so domain terms do not turn into noisy errors.

## AWS setup

See `docs/06_aws_bedrock_setup.md` for the full AWS/Bedrock configuration checklist, including:

- creating a named AWS profile
- enabling Bedrock model access for Claude
- using the Bedrock inference profile ID required by Claude Opus 4.6
- verifying credentials before running any real pipeline calls

**Never run Bedrock calls in CI.** The `MOCK_BEDROCK=true` env var or `--mock-bedrock` CLI flag
bypasses all AWS calls for local and CI testing.

## First mock run (no AWS required)

```bash
make mock-run
```

## First Bedrock smoke test

```bash
proposal-ingest bedrock-smoke-test
```

Verifies AWS profile, region, and Bedrock model access without processing any documents.

> **Note:** Requires valid AWS credentials and Bedrock model access. See `docs/06_aws_bedrock_setup.md`.

## Process one file

```bash
proposal-ingest process-file \
  --file sample_data/fake_source_root/2025/"2025 Fake DOE SBIR Battery Project"/"Technical Volume FINAL.docx" \
  --output-root tmp/file_test \
  --mock-bedrock
```

## Process one folder

```bash
proposal-ingest process-folder \
  --folder sample_data/fake_source_root/2025/"2025 Fake DOE SBIR Battery Project" \
  --output-root tmp/folder_test \
  --mock-bedrock
```

## Full pipeline

```bash
# 1. Scan and inventory
proposal-ingest scan \
  --source-root /path/to/source \
  --output-root /path/to/output

# 2. Analyze (use --mock-bedrock for testing)
proposal-ingest analyze \
  --output-root /path/to/output \
  --mock-bedrock

# 3. Synthesize canonical proposal-level records
proposal-ingest synthesize-proposals --output-root /path/to/output --mock-bedrock

# 4. Arbitrate proposal-level unresolved decisions into review questions
proposal-ingest arbitrate-questions --output-root /path/to/output --mock-bedrock

# 5. Export questions for human review
proposal-ingest export-questions --output-root /path/to/output

# 6. Answer output/review/questions_to_answer.csv in the simple GUI
proposal-ingest answer-questions --output-root /path/to/output

# 7. Apply answers (updates document and, for proposal-scoped rows, proposal records)
proposal-ingest apply-answers \
  --output-root /path/to/output \
  --answers-csv /path/to/output/review/questions_to_answer.csv

# 8. Build folder metadata and summaries (uses the proposal record above when present)
proposal-ingest build-folders --output-root /path/to/output

# 9. Build clean document set and S3 manifest
proposal-ingest build-clean-set --output-root /path/to/output
```

## Quality benchmarks and proposal-aware RAG output

`build-clean-set` writes a first-class RAG retrieval object for each proposal
(`retrieval/proposal_context.json` + `retrieval/document_manifest.jsonl` under
each proposal's mirror directory), a `proposal_metadata.json` copy of the
synthesized proposal record, a per-proposal `provenance_report.json`
explaining *why* documents were ranked and treated the way they were, and a
run-level `reports/quality_report.json` summarizing question counts,
document treatment, and Bedrock usage across the whole run. The S3/RAG
manifest (`manifests/s3_manifest.jsonl`) carries one `proposal_record` row
per proposal plus one `document` row per copied document, so a downstream
retrieval client can list proposal overviews first and drill into
authoritative or supporting documents from there. See
`docs/14_quality_benchmarks.md` for the full field reference.

Run the deterministic, mock-mode benchmark suite locally with:

```bash
proposal-ingest evaluate-quality \
  --source-root sample_data/quality_benchmark \
  --output-root tmp/quality_eval \
  --mock-bedrock \
  --expected tests/fixtures/quality_benchmark/expected
```

Add `--real-bedrock` (in place of `--mock-bedrock`) to compare real-model
synthesis against the same structural expectations locally; this is opt-in
and must never run in CI.

## Output structure

```
processed_output/
  review/
    questions_to_answer.csv
    answered_questions_archive.csv
    human_overrides.jsonl
  logs/
    run_YYYYMMDD_HHMMSS_<id>/
      run_manifest.json
      inventory/
        file_inventory.csv
        file_inventory.jsonl
        stray_files_ignored.csv
      document_metadata/
        all_document_metadata.jsonl
        by_document_id/<document_id>.json
      proposal_metadata/
        all_proposal_metadata.jsonl
        by_proposal_id/<proposal_id>.json
      arbitration/
        arbitrated_questions.jsonl
        arbitration_summary.json
      folder_metadata/<proposal_id>.json
      reports/
        excluded_files.csv
        processing_errors.csv
        bedrock_usage.csv
        quality_report.json
      manifests/
        s3_manifest.jsonl
      mirror/
        <year>/<proposal_branch>/
          folder_metadata.json
          folder_summary.md
          proposal_metadata.json
          provenance_report.json
          documents/
          metadata/
          retrieval/
            proposal_context.json
            document_manifest.jsonl
```

## Implementation status

The active product roadmap is [MVP-00 through MVP-10](docs/mvp/README.md). MVP-00 provides the
reproducible development baseline, MVP-01 provides the durable authenticated application and worker,
and MVP-02 provides the complete synthetic local product slice. Later work must follow the
acceptance boundaries in `docs/mvp/PR_PLAYBOOK.md`.

The reusable CLI prototype predates that roadmap. Its historical phases 1–12 and 14–16 are
implemented; its 2024 Phase 13 pilot remains a separate, incomplete historical effort and is not a
prerequisite for the 2025 product.

Implemented prototype capabilities include:

- Phase 1 — scanner and inventory
- Phase 2 — file rules and PowerPoint handling
- Phase 3 — metadata models and store
- Phase 4 — mock Bedrock mode
- Phase 5 — Bedrock smoke test
- Phase 6 — one-file Bedrock/mock processing
- Phase 7 — batch document analysis
- Phase 8 — human review question export and answer application
- Phase 9 — two-pass contextual analysis
- Phase 10 — grants tracker ingestion and overrides
- Phase 11 — folder metadata synthesis and Markdown summaries
- Phase 12 — clean document set, excluded-files report, and S3 manifest
- Phase 14 — canonical proposal-level synthesis (`synthesize-proposals`), consumed by folder synthesis
- Phase 15 — proposal-level question arbitration (`arbitrate-questions`), consumed by the human review loop
- Issue #9 — end-to-end quality benchmark suite, proposal-first-class RAG retrieval objects,
  enriched S3/RAG manifest relationships, provenance/quality reports, and `evaluate-quality`

Current implementation boundary:

- `scan`, `process-file`, `analyze`, `synthesize-proposals`, `arbitrate-questions`, `export-questions`, `answer-questions`, `apply-answers`, `build-folders`, `build-clean-set`, `evaluate-quality`, `process-folder`, `run-all`, and `bedrock-smoke-test` are wired.
- Use `--mock-bedrock` for local and CI-safe runs; real Bedrock paths require valid AWS credentials and model access.
- `run-all` now finishes by building the clean set and manifest unless critical review questions remain open.

See `docs/10_implementation_plan.md` and `docs/13_phase13_pilot_status.md` for archived prototype
history, not the next implementation sequence.

## Safety and confidentiality

**Never commit:**

- `.env`
- Source proposal documents (`source_documents/`)
- Processed output (`processed_output/`, `proposal-assistant-output/`)
- Raw model responses (`raw_model_responses/`)
- Private data, evaluations, screenshots, database dumps, or infrastructure state
- Logs (`logs/`, `*.log`)
- The grants tracker workbook
- Any file containing personal, financial, or partner-confidential information

The `.gitignore` blocks common paths, and `make secrets` scans candidate repository files. Neither
is an access-control boundary. Follow `docs/mvp/FIXTURE_AND_DATA_POLICY.md` and inspect `git status`
before every commit.

## Contributing

Use `codex/mvp-NN-short-purpose` branches for the product roadmap. Target `main` only with working,
tested code, a completed CodeRabbit review disposition, and Nicholas's manual merge.

```bash
git switch -c codex/mvp-NN-short-purpose
# ... implement, test ...
git push origin codex/mvp-NN-short-purpose
# open a pull request
```
