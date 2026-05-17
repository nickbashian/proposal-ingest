# 04 — Processing Pipeline Behavior

## Pipeline stages

### Stage 0 — Initialize run

Create a run ID:

```text
run_YYYYMMDD_HHMMSS_<short_random>
```

Write:

```text
processed_output/run_manifest.json
```

The manifest records:

- run ID
- command
- source root
- output root
- config snapshot
- git commit if available
- timestamp
- mock/real Bedrock mode

### Stage 1 — Scan

Input:

```bash
proposal-ingest scan --source-root <source-root> --output-root <output-root>
```

Behavior:

1. Detect year folders.
2. Treat each immediate child folder of a year folder as a proposal branch.
3. Ignore stray files directly under year folders.
4. Recursively scan files inside proposal branches.
5. Generate file hashes.
6. Apply file filters.
7. Detect exact duplicates.
8. Detect PowerPoint/PDF supersession.
9. Write inventory files.

Outputs:

```text
inventory/file_inventory.csv
inventory/file_inventory.jsonl
inventory/stray_files_ignored.csv
reports/excluded_files.csv
```

### Stage 2 — Tracker ingestion

Input:

```bash
proposal-ingest scan --tracker-path <path-to-tracker>
```

or config:

```yaml
tracker:
  enabled: true
  path: "C:/.../General/Empower Grant Activities/Grants In Progress/...xlsx"
```

Behavior:

1. Load tracker workbook.
2. Normalize columns.
3. Write `tracker/tracker_rows.jsonl`.
4. Use tracker rows as contextual data for later AI matching.
5. Do not include tracker in clean RAG set.

Matching approach:

- Do not hardcode matching on folder names.
- Let AI match proposal branches to tracker rows using branch-level summaries, document metadata, and tracker rows.
- Use tracker as high-authority for dates/status/results after match.
- Record disagreements.

### Stage 3 — Pass 1 document analysis

Input:

```bash
proposal-ingest analyze --output-root <output-root>
```

Behavior:

For each eligible file:

1. Skip if same hash already processed unless `--force` is used.
2. Choose processing strategy.
3. Build prompt context.
4. Call Bedrock or mock client.
5. Validate response with Pydantic.
6. If invalid JSON, run one repair prompt.
7. If still invalid, save failure and continue.
8. Save metadata.
9. Export questions if needed.

Processing strategy:

```text
if unsupported: inventory_only
elif powerpoint: inventory_only_or_superseded
elif excel and tiny/simple: direct_bedrock_optional
elif excel: local_extract_then_bedrock
elif file_size <= max_direct_upload_mb and extension supported by DocumentBlock: direct_bedrock
else: local_extract_then_bedrock
```

Direct document formats:

```text
pdf, csv, doc, docx, xls, xlsx, html, txt, md
```

PowerPoint is intentionally excluded from direct processing in MVP.

### Stage 4 — Two-pass contextual review

Purpose:

Some files cannot be classified confidently without branch context. Example: a vague support letter may only make sense when the model knows it belongs to a specific Air Force SBIR proposal.

Pass 2 trigger conditions:

- `confidence.document_category < 0.65`
- `confidence.document_role < 0.65`
- `confidence.include_in_future_rag < 0.65`
- `origin_type = unknown`
- `canonical_proposal_name = unknown`
- AI explicitly sets `needs_context_pass2 = true`
- important file has ambiguous inclusion status

Pass 2 context packet:

- proposal branch name and year folder, clearly labeled as low-trust metadata
- list of high-confidence documents in same branch
- folder-level preliminary summary if available
- tracker candidate rows if any
- Pass 1 metadata for the current document
- the current document or extracted representation

Pass 2 merge policy:

- Do not overwrite high-confidence Pass 1 fields unless Pass 2 confidence is higher and explanation is provided.
- Prefer replacing `unknown` fields with Pass 2 values when confidence is moderate/high.
- Preserve both pass outputs in metadata history.
- Log changed fields.

Outputs:

```text
document_metadata/by_document_id/<document_id>.json
reports/pass2_changes.csv
```

### Stage 5 — Question export

Input:

```bash
proposal-ingest export-questions --output-root <output-root>
```

Behavior:

- Collect active non-low-priority questions.
- Limit to max 5 per file, target 3.
- Deduplicate stable questions across runs.
- Generate global CSV.

Output:

```text
review/questions_to_answer.csv
```

### Stage 6 — Apply answers

Input:

```bash
proposal-ingest apply-answers --output-root <output-root>
```

Behavior:

- Read CSV.
- Apply rows with non-empty `user_answer` and `status` not already applied.
- Update allowed metadata fields deterministically.
- Archive applied answers.
- Do not call model in MVP.

Allowed patch fields:

- `canonical_proposal_name`
- `agency`
- `program`
- `topic_number`
- `status`
- `award_status`
- `document_category`
- `document_role`
- `origin_type`
- `version_status`
- `include_in_clean_set`
- `include_in_future_rag`
- `rag_priority`
- `sensitivity_labels`
- `manual_review_required`
- `operator_notes`

### Stage 7 — Folder synthesis

Input:

```bash
proposal-ingest build-folders --output-root <output-root>
```

Behavior:

- Gather document metadata by proposal branch.
- Incorporate tracker match if available.
- Generate folder-level metadata.
- Generate Markdown summary.
- Identify key documents.
- Count included, excluded, and manual-review files.
- Set readiness flags.

Outputs:

```text
folder_metadata/<proposal_id>.json
mirror/<year>/<proposal_branch>/folder_metadata.json
mirror/<year>/<proposal_branch>/folder_summary.md
```

### Stage 8 — Clean set build

Input:

```bash
proposal-ingest build-clean-set --output-root <output-root>
```

Behavior:

- Stop if critical questions remain unless `--allow-critical-open` is used.
- Copy selected files into flattened `documents/` folders.
- Clean filenames for downstream compatibility.
- Do not copy excluded files.
- Copy per-document metadata into `metadata/`.
- Generate excluded files report.
- Generate S3 manifest.

Filename safety:

- Preserve original name as much as possible.
- Replace unsafe characters with `_`.
- Avoid collisions by appending short hash if needed.

### Stage 9 — S3 manifest generation

Output only for MVP. No upload required.

Each row:

```json
{
  "document_id": "doc_abcd1234",
  "proposal_id": "prop_2025_xxx",
  "local_clean_path": ".../documents/Technical Volume.docx",
  "metadata_path": ".../metadata/doc_abcd1234.json",
  "recommended_s3_key": "proposal-history/2025/prop_2025_xxx/documents/Technical_Volume.docx",
  "include_in_future_rag": true,
  "rag_priority": "high"
}
```

## Error handling

Default behavior: log and continue.

Fatal errors:

- invalid config
- output root cannot be written
- source root missing
- schema code broken

Non-fatal errors:

- individual file read error
- Bedrock failure for one file
- model returns invalid JSON after repair
- local extraction failure
- tracker parse failure

## Resumability

The pipeline should skip work when possible.

Skip criteria:

- same file hash processed under same schema version
- metadata exists and `--force` is not used
- raw file unchanged

Force modes:

- `--force`: reprocess all eligible files
- `--force-document <document_id>`: reprocess one document
- `--force-folder <proposal_id>`: reprocess one folder
- `--force-pass2`: rerun contextual pass

## Dry run

`--dry-run` should scan and report intended actions without calling Bedrock or copying files.
