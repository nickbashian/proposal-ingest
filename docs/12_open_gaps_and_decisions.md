# 12 — Open Gaps and Decisions

This spec is ready to start coding. The following items can be deferred, but they are worth keeping visible.

## Gaps to fill before broad real-data processing

### 1. Exact grants tracker path and workbook filename

Known parent path:

```text
General\Empower Grant Activities\Grants In Progress
```

Still needed:

- exact workbook filename
- whether there are multiple tracker files
- whether there are old/archived copies to ignore

This is not blocking scanner development.

### 2. Actual tracker sheet name and header row

Known columns:

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

Still needed:

- sheet name
- whether the header row is row 1
- whether merged cells or title rows exist

Not blocking; parser can support configurable sheet/header row.

### 3. Real Bedrock file-size behavior

Spec default is 20 MB, but some document-chat examples and workflows use lower practical limits. Keep this configurable and test early.

### 4. Excel extraction policy

MVP says Excel should be extracted locally first unless tiny/simple. The implementation still needs a definition of tiny/simple.

Suggested default:

```text
Tiny/simple Excel = <= 3 sheets, <= 500 non-empty cells total, file size <= 1 MB
```

This can be changed after real tests.

### 5. Budget treatment

Budgets are excluded from future RAG by default, but clean-set inclusion may vary.

Suggested MVP rule:

```text
Budget files: include_in_future_rag=false, include_in_clean_set=false unless manually approved.
```

### 6. Final vs draft heuristics

The model should classify final/draft, but Python can also use filename clues as weak signals.

Suggested weak filename clues:

- final, submitted, submission, signed -> likely final/submitted
- draft, v1, v2, working, old -> likely draft/working

These should never override AI/human metadata by themselves.

### 7. PowerPoint future path

MVP only inventories PowerPoints. Future options:

- process PowerPoint directly if Bedrock support appears
- convert PPTX to PDF locally
- extract slide text with `python-pptx`
- export slides as images/PDF via LibreOffice
- run separate `process-powerpoints` command

### 8. OCR

OCR is out of scope. Scanned PDFs should be marked only when there is specific evidence:

- extracted text is near-zero
- file has many pages
- PDF appears image-based

Future OCR could use AWS Textract or local OCR, but do not add now.

### 9. Near-duplicate detection

MVP handles exact duplicate hashes only. Later, add near-duplicate detection using:

- normalized title matching
- file stem similarity
- text fingerprinting
- embedding similarity

### 10. Future S3 upload

MVP generates a manifest only. Later upload command should:

- upload clean documents
- upload metadata sidecars
- preserve S3 keys from manifest
- optionally apply object metadata/tags
- optionally trigger Bedrock Knowledge Base sync

## Decisions already made

- Local-first prototype.
- No mutation of source folders.
- Separate output root.
- JSON/JSONL is source of truth.
- CSV is for human review.
- Bedrock/Opus 4.6 default.
- Direct document upload first, fallback to local extraction.
- Excel local extraction first.
- PowerPoint inventory-only unless same-name PDF exists.
- OCR out of scope.
- Use two-pass contextual analysis for low-confidence files.
- Tracker is high-authority for dates/status/results.
- Use Python 3.13 target with practical fallback to 3.12.
- Use Ruff, pytest, mypy, Makefile, GitHub Actions.

## Recommended next step

Start with `Prompt 1 — Repo bootstrap`, then commit. Do not start Bedrock integration until scanner, inventory, file rules, and metadata models are working in mock mode.
