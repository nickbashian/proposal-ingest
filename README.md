# proposal-ingest

Local-first document ingestion and metadata pipeline for a historical grant/proposal archive.

## What this tool does

- Scans a read-only local folder tree and builds a complete file inventory.
- Filters, hashes, and deduplicates files; handles PowerPoint/PDF supersession.
- Sends supported documents to Amazon Bedrock (Claude) for metadata extraction and classification.
- Supports a human question-and-answer correction loop via CSV.
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
  pyproject.toml            Python project definition and dependency list
  Makefile                  Developer shortcuts (install, lint, test, check)
  .env.example              Environment variable template (copy to .env)
  .gitignore                Excludes confidential data, environments, build artifacts
  .github/workflows/ci.yml  GitHub Actions CI (Black, Ruff, spell check, mypy, pytest — no real Bedrock)
  config/
    default_config.yaml     Default runtime configuration
    document_type_rules.yaml  File type inclusion/exclusion rules
  prompts/                  Bedrock prompt templates
  schemas/                  JSON Schema definitions for metadata records
  src/proposal_ingest/      Python package source
  tests/                    pytest test suite
  sample_data/              Fake synthetic proposal files for local testing (no real data)
  sample_outputs/           Reference output column layouts and example JSONL
  docs/                     Full specification documents
```

## Setup

### Requirements

- Python 3.13 (fallback: 3.12 if a dependency causes friction)
- Git
- AWS CLI with a configured named profile (for Bedrock calls only)

### Install

```bash
git clone https://github.com/nickbashian/proposal-ingest.git
cd proposal-ingest

# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # macOS/Linux

# Install the package and dev dependencies
pip install -e ".[dev]"
```

### Configure

Copy `.env.example` to `.env` and fill in your local paths:

```bash
copy .env.example .env
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
make check   # runs Black check, Ruff, spell check, mypy, pytest
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
make precommit-run  # pre-commit run --all-files
make mypy    # mypy src
make test    # pytest
```

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
proposal-ingest run-all \
  --source-root sample_data/fake_source_root \
  --output-root tmp/mock_output \
  --mock-bedrock
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

# 3. Export questions for human review
proposal-ingest export-questions --output-root /path/to/output

# 4. Answer output/review/questions_to_answer.csv in the simple GUI
proposal-ingest answer-questions --output-root /path/to/output

# 5. Apply answers
proposal-ingest apply-answers \
  --output-root /path/to/output \
  --answers-csv /path/to/output/review/questions_to_answer.csv

# 6. Build folder metadata and summaries
proposal-ingest build-folders --output-root /path/to/output

# 7. Build clean document set and S3 manifest
proposal-ingest build-clean-set --output-root /path/to/output
```

## Output structure

```
processed_output/
  review/
    questions_to_answer.csv
    answered_questions_archive.csv
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
      folder_metadata/<proposal_id>.json
      reports/
        excluded_files.csv
        processing_errors.csv
        bedrock_usage.csv
      manifests/
        s3_manifest.jsonl
      mirror/
        <year>/<proposal_branch>/
          folder_metadata.json
          folder_summary.md
          documents/
          metadata/
```

## Implementation status

Phases 1 through 12 are complete:

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

Current implementation boundary:

- `scan`, `process-file`, `analyze`, `export-questions`, `answer-questions`, `apply-answers`, `build-folders`, `build-clean-set`, `process-folder`, `run-all`, and `bedrock-smoke-test` are wired.
- Use `--mock-bedrock` for local and CI-safe runs; real Bedrock paths require valid AWS credentials and model access.
- `run-all` now finishes by building the clean set and manifest unless critical review questions remain open.

See `docs/10_implementation_plan.md` for the phase-by-phase status and `docs/11_copilot_agent_prompts.md`
for the ready-to-use Copilot/agent prompts for later phases.

**Suggested branch order:**

1. `feature/scanner-inventory` — Prompt 2 in the spec
2. `feature/metadata-models` — Prompt 4
3. `feature/mock-bedrock` — Prompt 5
4. `feature/bedrock-smoke-test` — Prompt 6
5. `feature/document-analysis` — Prompts 7–8
6. `feature/question-loop` — Prompt 9
7. `feature/folder-clean-output` — Prompts 10–11

## Safety and confidentiality

**Never commit:**

- `.env`
- Source proposal documents (`source_documents/`)
- Processed output (`processed_output/`, `proposal-assistant-output/`)
- Raw model responses (`raw_model_responses/`)
- Logs (`logs/`, `*.log`)
- The grants tracker workbook
- Any file containing personal, financial, or partner-confidential information

The `.gitignore` blocks these paths by default. If in doubt, check with `git status` before
every commit.

## Contributing

Use feature branches. Target `main` only with working, tested code.

```bash
git checkout -b feature/scanner-inventory
# ... implement, test ...
git push origin feature/scanner-inventory
# open a pull request
```
