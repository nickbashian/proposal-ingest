# 11 — Copilot / Coding Agent Prompts

Use these prompts one at a time. Keep the agent scoped. Ask for tests in the same chunk when possible.

## Prompt 1 — Repo bootstrap

```text
You are helping build a Python 3.13 prototype package called `proposal-ingest` for local document ingestion and metadata generation.

Create the initial repo scaffold using a `src/proposal_ingest` layout. Use Typer for the CLI, Pydantic for schemas, Ruff for lint/formatting, pytest for tests, and mypy for type checking. Add a Makefile with install, format, lint, mypy, test, and check targets. Add a basic GitHub Actions workflow that installs the package and runs Ruff, mypy, and pytest. Add `.env.example` and `.gitignore` entries for source documents, processed outputs, logs, raw model responses, and `.env`.

Do not implement the full pipeline yet. Implement placeholder CLI commands: scan, analyze, export-questions, apply-answers, build-folders, build-clean-set, run-all, process-folder, process-file, and bedrock-smoke-test. Each command should print a clear placeholder message.

Add minimal tests that verify the CLI imports and `proposal-ingest --help` runs.
```

## Prompt 2 — Scanner and inventory

```text
Implement the scanner and inventory generator for the proposal-ingest package.

Rules:
- Source root is read-only.
- Detect year folders under the source root by folder names that look like four-digit years.
- Each immediate child folder under a year folder is one proposal branch.
- Ignore stray files directly under year folders and log them to `inventory/stray_files_ignored.csv`.
- Recursively scan files inside proposal branches.
- Skip hidden/system files and temporary Office files beginning with `~$`.
- Compute SHA-256 for each file.
- Generate a stable `proposal_id` and `document_id`.
- Write both `inventory/file_inventory.csv` and `inventory/file_inventory.jsonl`.
- Never modify source files.

Add tests using a fake temporary folder tree.
```

## Prompt 3 — File filters and PowerPoint/PDF supersession

```text
Add file filtering logic.

Supported MVP processing extensions: .pdf, .docx, .doc, .xlsx, .xls, .csv, .txt, .md.

Rules:
- Images are ignored.
- ZIP files are inventory-only.
- PowerPoint files (.ppt, .pptx) are inventory-only by default.
- If a PowerPoint has a same-stem PDF in the same folder, mark the PowerPoint as `superseded_by_pdf` and store the PDF document_id as `superseded_by_document_id` if available.
- If a PowerPoint has no same-stem PDF, create a review question field in the inventory or a separate question record indicating it may need future special processing.
- Unsupported files are inventory-only with a skip reason.

Add tests for all file type cases and same-stem PDF supersession.
```

## Prompt 4 — Pydantic schemas and metadata store

```text
Implement Pydantic models for inventory records, document metadata, folder metadata, review questions, Bedrock usage records, and S3 manifest rows.

Use the spec documents in `docs/03_metadata_schema.md` as the source of truth. Allow unknown values for AI-inferred fields. Require confidence scores for major inferred fields. Add validation for enums.

Implement a metadata store module that writes:
- document metadata JSON by document_id
- all document metadata as JSONL
- folder metadata JSON
- run manifests

Add tests for validation success/failure and JSON/JSONL writing.
```

## Prompt 5 — Mock Bedrock mode

```text
Implement mock Bedrock analysis mode.

The mock analyzer should accept an inventory record and return deterministic valid document metadata without making network calls. It should infer obvious categories from filename/extension only, but mark confidence as low/moderate and include `generated_by: mock_bedrock`.

Wire this into `proposal-ingest analyze --mock-bedrock` and `proposal-ingest process-file --mock-bedrock`.

Add tests that run scan + analyze in mock mode and validate metadata outputs.
```

## Prompt 6 — Bedrock smoke test

```text
Implement the Bedrock client wrapper and `bedrock-smoke-test` command.

Requirements:
- Load AWS_PROFILE, AWS_REGION, BEDROCK_MODEL_ID, and BEDROCK_MODEL_LABEL from env/config.
- Default region: us-east-1.
- Default model ID: anthropic.claude-opus-4-6-v1.
- Use boto3 bedrock-runtime client and the Converse API.
- Send a small text-only prompt.
- Print model ID, region, and a short response.
- Log success/failure.

Do not add document processing yet.
```

## Prompt 7 — One-file Bedrock document analysis

```text
Implement `process-file` for one real document.

Requirements:
- Load prompt templates from `prompts/`.
- Choose direct DocumentBlock path for supported documents under `MAX_DIRECT_UPLOAD_MB`, except Excel files unless tiny/simple.
- Use local extraction fallback for supported files.
- Require model output to be JSON.
- Validate with Pydantic.
- If invalid JSON, run one repair prompt and retry validation.
- If still invalid, save failure and continue without crashing.
- Save raw model response when `--save-raw-responses` is set.
- Write Bedrock usage records.

Add a dry-run mode and mock mode for this command.
```

## Prompt 8 — Batch analyze command

```text
Implement `analyze` for batch processing inventory records.

Rules:
- Skip already-processed hashes unless --force is used.
- Log and continue on per-file errors.
- Respect --limit for testing.
- Support --mock-bedrock.
- Write document metadata and usage logs.
- Set processing statuses correctly.

Add integration tests with fake documents and mock mode.
```

## Prompt 9 — Human review CSV

```text
Implement the human review workflow.

Requirements:
- Export global `review/questions_to_answer.csv` from questions generated in document metadata plus Python-generated questions such as PowerPoint special-processing questions.
- Suppress low-priority questions by default.
- Limit to max 5 questions per file.
- Generate stable question IDs.
- Implement `apply-answers` to update allowed metadata fields deterministically without calling the model.
- Archive applied answers.
- Log invalid answers.

Add tests for question generation, deduplication, answer application, and invalid answer handling.
```

## Prompt 10 — Folder synthesis

```text
Implement folder-level metadata synthesis.

Requirements:
- Gather document metadata by proposal_id.
- Use tracker metadata if available and matched.
- Create folder metadata JSON.
- Create a human-readable folder_summary.md.
- Count included, excluded, and manual-review documents.
- Identify key documents.
- Set readiness flags.
- In mock mode, generate deterministic folder summaries without Bedrock.

Add tests using fake document metadata.
```

## Prompt 11 — Clean set builder and S3 manifest

```text
Implement the clean set builder.

Rules:
- Stop if critical open questions remain unless --allow-critical-open is used.
- Copy only files where include_in_clean_set is true and manual_review_required is false unless explicitly overridden.
- Flatten selected files into `mirror/<year>/<proposal_branch>/documents/`.
- Sanitize filenames while preserving original names as much as possible.
- Resolve filename collisions with short hashes.
- Copy metadata into `metadata/`.
- Write `folder_metadata.json` and `folder_summary.md` into each mirrored branch.
- Write `reports/excluded_files.csv`.
- Write `manifests/s3_manifest.jsonl`.

Add tests for copy behavior, collision handling, excluded files, and manifest generation.
```

## Prompt 12 — Two-pass contextual analysis

```text
Implement the two-pass contextual analysis system.

Requirements:
- Identify low-confidence document metadata records using configurable thresholds.
- Build a context packet from other documents in the same proposal branch, including high-confidence document summaries, proposal-level clues, and tracker candidates if available.
- Re-run the flagged document with `pass2_contextual_review_system.md`.
- Merge Pass 2 results conservatively: do not overwrite high-confidence Pass 1 fields unless Pass 2 confidence is higher and includes an explanation.
- Save metadata history and a `reports/pass2_changes.csv` report.
- Add tests with mock Pass 2 responses.
```

## Prompt 13 — Grants tracker integration

```text
Implement grants tracker ingestion.

Known tracker fields include: grant org, grant number, name, issue date, concept paper due date, concept paper notification, submission due date, selection notification, award date, comments, and link.

Requirements:
- Tracker path is configurable.
- Parse the workbook with pandas/openpyxl.
- Normalize column names.
- Write `tracker/tracker_rows.jsonl`.
- Do not include tracker workbook in clean RAG document set.
- Add data structures for tracker row matching, but keep AI-assisted matching as a separate function.
- Tracker fields override AI guesses for dates/status/results after a match, but not canonical names without review.
- Record disagreements.

Add tests using a fake tracker workbook.
```
