# 01 — Product Requirements

## Personas

### Primary operator

The primary operator is a technical founder/CTO who has a local archive of grant applications and wants to convert it into a cleaned, metadata-rich corpus for future proposal assistance.

### Future RAG system

The future RAG system will consume the cleaned document set and associated metadata. It needs stable IDs, structured metadata, clean source files, and S3-ready manifests.

## Requirements

### R1 — Source folder scanning

The system shall recursively scan a programmable local source root.

Acceptance criteria:

- The source root is provided by CLI argument or config.
- The source root is never modified.
- Year folders from 2023–2026 are supported without hardcoding those years.
- Each immediate child folder under a year folder is treated as one proposal branch.
- Stray files directly inside year folders are ignored and logged.
- Nested folders inside proposal branches are scanned.

### R2 — File inventory

The system shall generate a deterministic inventory before AI processing.

Inventory fields:

- `document_id`
- `proposal_id`
- `source_path`
- `relative_path`
- `year_folder`
- `proposal_branch`
- `file_name_original`
- `file_name_safe`
- `extension`
- `size_bytes`
- `modified_time`
- `sha256`
- `eligible_for_processing`
- `processing_strategy`
- `processing_status`
- `skip_reason`
- `duplicate_of_document_id`
- `superseded_by_document_id`

### R3 — File type filtering

Supported MVP processing types:

- `.pdf`
- `.docx`
- `.doc`
- `.xlsx`
- `.xls`
- `.csv`
- `.txt`
- `.md`

PowerPoint handling:

- `.pptx` and `.ppt` are scanned and inventoried.
- They are not processed by default.
- If a same-name PDF exists in the same folder, mark the PowerPoint as `superseded_by_pdf` and process the PDF.
- If no same-name PDF exists, add a review question asking whether special processing is needed later.

Ignored or inventory-only types:

- Images are ignored.
- ZIP files are inventoried only.
- Temporary Office files are ignored.
- Hidden/system files are skipped.

### R4 — Bedrock analysis

The system shall analyze eligible documents using Amazon Bedrock with `opus-4.6` as the default model label.

Acceptance criteria:

- Actual model ID is configurable.
- Default model ID is `us.anthropic.claude-opus-4-6-v1`.
- Region defaults to `us-east-1`.
- Direct document processing is attempted first for eligible files under the configured size limit, except Excel files.
- Maximum direct upload size defaults to 20 MB and is configurable.
- Excel files use local extraction first unless tiny/simple.
- Local extraction fallback is available for supported types.
- Failures are logged and do not halt the full run.

### R5 — Two-pass contextual analysis

The system shall support contextual re-analysis of low-confidence documents.

Pass 1:

- Analyze each document with local file/folder context and source path metadata.
- Save structured metadata and confidence scores.
- Flag low-confidence, ambiguous, or context-dependent files.

Pass 2:

- After enough branch-level metadata exists, re-run flagged documents with summarized context from other files in the proposal branch.
- Pass 2 should not overwrite high-confidence fields unless confidence improves or the original field was unknown.
- All changes must be logged.

### R6 — Grants tracker integration

The system shall use a grants tracker workbook as a global metadata source.

Known tracker location pattern:

```text
General\Empower Grant Activities\Grants In Progress
```

Known tracker fields:

- grant org
- grant number
- name
- issue date
- concept paper due date
- concept paper notification
- submission due date
- selection notification
- award date
- comments
- link

Acceptance criteria:

- Tracker path is configurable.
- Tracker is not included in the clean RAG document set.
- Tracker metadata is high-authority for dates, status, and results.
- Tracker should not override canonical proposal names without review.
- AI may attempt to match proposal folders to tracker rows.
- Match confidence and disagreements are recorded.

### R7 — Human review loop

The system shall generate a global `questions_to_answer.csv`.

Acceptance criteria:

- Low-priority questions are suppressed by default.
- Target maximum is 3 questions per file; hard maximum is 5.
- Questions must only be asked when the answer changes downstream behavior.
- Suggested answers are supplied when applicable.
- Manual corrections can update selected metadata fields.
- Answers are applied deterministically without an AI recall in MVP.
- Question IDs remain stable across runs.

### R8 — Metadata and validation

The system shall store structured metadata as JSON/JSONL and validate it with Pydantic models.

Acceptance criteria:

- Model output must pass schema validation.
- Invalid JSON triggers one repair prompt.
- If repair fails, save the failure and continue.
- The model may answer `unknown` instead of guessing.
- Confidence scores are required for major inferred fields.

### R9 — Clean output generation

The system shall generate a separate local output root.

Acceptance criteria:

- Excluded files are not copied.
- Selected files are copied into flattened `documents/` folders per proposal branch.
- Original filenames are preserved where safe.
- Special characters are cleaned during copy to avoid downstream system issues.
- Associated metadata is copied into a `metadata/` folder.
- Folder summaries are generated as Markdown.
- Excluded files are reported in CSV.
- S3 manifests are generated locally.

### R10 — Development quality

The repo shall include basic engineering hygiene.

Acceptance criteria:

- Python 3.13 target.
- `venv` or conda workflow documented.
- Ruff for linting and formatting.
- Pytest for tests.
- Mypy included.
- Makefile included.
- Basic GitHub Actions CI included.
- `.env`, raw outputs, source documents, logs, and processed output are gitignored.
- Sample fake documents are included for tests.
