# 02 — System Architecture

## Architecture summary

The prototype is a local-first batch pipeline with deterministic Python orchestration and focused Bedrock calls. The AI proposes metadata; the local metadata store is the system of record.

```text
Local source root  ──scan──>  File inventory
                               │
                               ├──filter/hash/dedupe/supersession
                               │
                               ├──analyze with Bedrock or mock mode
                               │       │
                               │       ├──document metadata JSON
                               │       ├──raw model response optional
                               │       └──questions for user
                               │
                               ├──two-pass contextual review
                               │
                               ├──human CSV review/apply answers
                               │
                               ├──folder-level synthesis
                               │
                               └──clean mirrored output + S3 manifest
```

## Core principle

Do not let the model own the workflow. Python owns orchestration, state, validation, resumability, and file movement. The model performs classification, extraction, summarization, uncertainty flagging, and contextual reasoning.

## Proposed repo structure

```text
proposal-ingest/
  README.md
  pyproject.toml
  Makefile
  .env.example
  .gitignore
  config/
    default_config.yaml
    document_type_rules.yaml
  prompts/
    document_metadata_system.md
    document_metadata_user.md
    document_metadata_repair.md
    folder_metadata_system.md
    folder_metadata_user.md
    pass2_contextual_review_system.md
  schemas/
    document_metadata.schema.json
    folder_metadata.schema.json
  src/
    proposal_ingest/
      __init__.py
      cli.py
      config.py
      scanner.py
      file_filters.py
      hashing.py
      powerpoints.py
      tracker.py
      extractors.py
      bedrock_client.py
      mock_bedrock.py
      prompts.py
      schemas.py
      metadata_store.py
      question_loop.py
      two_pass.py
      folder_builder.py
      clean_set_builder.py
      s3_manifest.py
      logging_utils.py
      path_utils.py
  tests/
    test_scanner.py
    test_file_filters.py
    test_powerpoint_supersession.py
    test_metadata_validation.py
    test_question_loop.py
    test_clean_set_builder.py
  sample_data/
    fake_source_root/
    fake_tracker/
```

## Module responsibilities

### `cli.py`

Defines command-line entry points.

Commands:

- `scan`
- `analyze`
- `export-questions`
- `apply-answers`
- `build-folders`
- `build-clean-set`
- `run-all`
- `process-folder`
- `process-file`
- `bedrock-smoke-test`

### `config.py`

Loads config from:

1. default YAML
2. `.env`
3. CLI overrides

CLI overrides win.

### `scanner.py`

Discovers proposal branches, scans files, and creates inventory records.

Rules:

- Year folders are detected by four-digit names, but not hardcoded to specific years.
- Immediate child folders under year folders are proposal branches.
- Stray files directly under year folders are ignored and logged.
- Nested files under proposal branches are scanned.

### `file_filters.py`

Determines eligibility and preliminary processing status.

Examples:

- ignore temporary Office files beginning with `~$`
- skip hidden/system files
- ignore images
- inventory ZIP files only
- mark unsupported types

### `powerpoints.py`

Handles PowerPoint-specific MVP behavior.

- Inventory `.pptx`/`.ppt`.
- Search same folder for same-stem `.pdf`.
- Mark PowerPoint as `superseded_by_pdf` if PDF exists.
- If no PDF exists, generate review question for potential future processing.

### `hashing.py`

Computes stable SHA-256 hashes.

Uses:

- exact duplicate detection
- resumability
- stable `document_id` generation

### `tracker.py`

Loads the grants tracker workbook and converts it into a structured global metadata source.

Responsibilities:

- parse configured tracker path
- normalize tracker columns
- expose tracker rows for AI-assisted matching
- save tracker-derived metadata cache

### `extractors.py`

Local extraction fallback.

MVP extractors:

- PDF text extraction with page count and extracted character count
- DOCX text extraction
- XLSX/XLS sheet previews, sheet names, dimensions, non-empty cells, small tables
- CSV preview
- TXT/MD passthrough

OCR is out of scope.

### `bedrock_client.py`

Wraps Bedrock Runtime calls.

Responsibilities:

- model ID mapping from friendly label to Bedrock model ID
- direct DocumentBlock request where supported
- local-extract request path
- retry behavior
- usage/latency logging
- raw response save toggle

### `mock_bedrock.py`

Returns deterministic fake metadata for local testing without AWS calls.

### `schemas.py`

Pydantic models for:

- inventory records
- document metadata
- folder metadata
- review questions
- tracker rows
- S3 manifest rows

### `metadata_store.py`

System of record for all metadata.

Writes:

- `document_metadata/all_documents.jsonl`
- `document_metadata/by_document_id/<document_id>.json`
- `folder_metadata/<proposal_id>.json`
- `runs/<run_id>/run_manifest.json`

### `question_loop.py`

Generates, updates, and applies `questions_to_answer.csv`.

### `two_pass.py`

Implements contextual re-analysis.

- identifies low-confidence records
- builds proposal-branch context packet
- re-runs model call
- merges changes conservatively

### `folder_builder.py`

Synthesizes proposal-branch metadata and Markdown summaries from document metadata.

### `clean_set_builder.py`

Copies selected documents into clean output folders.

### `s3_manifest.py`

Generates local S3 manifest JSONL.

## Output directory structure

```text
processed_output/
  run_manifest.json
  inventory/
    file_inventory.csv
    file_inventory.jsonl
    stray_files_ignored.csv
  tracker/
    tracker_rows.jsonl
    tracker_matches.csv
  document_metadata/
    all_documents.jsonl
    by_document_id/
      <document_id>.json
  folder_metadata/
    <proposal_id>.json
  review/
    questions_to_answer.csv
    answered_questions_archive.csv
  reports/
    excluded_files.csv
    processing_errors.csv
    bedrock_usage.csv
  manifests/
    s3_manifest.jsonl
  debug/
    raw_model_responses/
  mirror/
    2025/
      2025 DOD SBIR AF251 Li-ion/
        folder_metadata.json
        folder_summary.md
        documents/
        metadata/
        review/
```

## Stable IDs

### `proposal_id`

Generated independently of local absolute path.

Suggested formula:

```text
proposal_id = "prop_" + slug(year_folder + "__" + proposal_branch_name) + "__" + short_hash(relative_branch_path)
```

Folder names are not trusted as metadata, but they are acceptable as part of an ID if paired with hash.

### `document_id`

Suggested formula:

```text
document_id = "doc_" + sha256(file_bytes)[0:16]
```

For exact duplicate files, the same content hash produces the same `document_id`. The inventory can record multiple source paths pointing to the same document.

## State transitions

```text
discovered
skipped_hidden_or_system
skipped_temp_office_file
ignored_stray_year_file
unsupported_file_type
inventory_only
superseded_by_pdf
pending_analysis
processed_pass1
needs_context_pass2
processed_pass2
needs_user_answer
answers_applied
ready_for_folder_synthesis
included_in_clean_set
excluded_from_clean_set
error
```
