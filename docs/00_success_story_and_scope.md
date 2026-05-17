# 00 — Success Story and Scope

## Success story

As the operator of the Proposal Assistant ingestion tool, I want to point the pipeline at a programmable local source root containing nested historical grant and proposal folders, so that the system can scan the archive without modifying it, classify both opportunity/source documents and generated proposal-response documents, generate document-level and folder-level metadata using Amazon Bedrock, ask targeted clarification questions only when answers change downstream behavior, apply my answers, and produce a clean mirrored output folder containing selected documents and validated metadata ready for later S3 upload and RAG ingestion.

## Key distinction: opportunity documents vs. generated response documents

Proposal folders contain two broad classes of material:

1. **Opportunity/source documents**
   - RFPs, FOAs, topic descriptions, solicitation instructions, evaluation criteria, agency templates, compliance documents, DFARS clauses, and terms and conditions.
   - These documents provide context for what the proposal was responding to.
   - Many are boilerplate-heavy and should not dominate future RAG retrieval.

2. **Generated response documents**
   - Technical volumes, project descriptions, budgets, letters of support, quad charts, commercialization plans, abstracts, summaries, work plans, final reports, review feedback, and project deliverables.
   - These are usually more valuable for future proposal reuse and company knowledge.

The pipeline must classify this distinction at document level using `origin_type`, `document_category`, `document_role`, and RAG treatment metadata.

## Prototype goals

- Scan nested local proposal folders in a read-only manner.
- Treat each immediate child folder under a year folder as one proposal branch.
- Ignore stray files directly inside year folders.
- Capture folder names as low-confidence metadata only.
- Build a deterministic file inventory before any AI calls.
- Use document hashes to support resumability and exact duplicate handling.
- Process PDF, Word, Excel, CSV, TXT, and Markdown files.
- Inventory PowerPoints but do not process by default.
- Detect PowerPoint files superseded by same-name PDFs in the same folder.
- Use Bedrock/Claude Opus 4.6 for structured metadata generation.
- Use a two-pass contextual review for low-confidence documents.
- Generate a global `questions_to_answer.csv` for manual review.
- Apply user answers deterministically without a model recall unless explicitly requested later.
- Produce folder-level metadata and Markdown summaries.
- Copy selected documents into flattened `documents/` folders under a separate output root.
- Generate local S3 upload manifests for future use.
- Include basic code quality tooling, tests, documentation, and CI.

## Non-goals for MVP

- No web UI.
- No live S3 upload required.
- No AWS Knowledge Base creation or sync.
- No vector database.
- No full PowerPoint processing pipeline.
- No OCR pipeline.
- No near-duplicate detection beyond exact hash matches.
- No complex autonomous agent that modifies source files.
- No automatic redaction.
- No multi-user review workflow.

## Definition of done for MVP

The MVP is done when the following workflow works on a small real subset of proposal folders:

```bash
proposal-ingest scan --source-root "C:\path\to\Empower Grant Activities - Documents" --output-root "C:\path\to\proposal-assistant-output"
proposal-ingest analyze --output-root "C:\path\to\proposal-assistant-output"
proposal-ingest export-questions --output-root "C:\path\to\proposal-assistant-output"
proposal-ingest apply-answers --output-root "C:\path\to\proposal-assistant-output"
proposal-ingest build-folders --output-root "C:\path\to\proposal-assistant-output"
proposal-ingest build-clean-set --output-root "C:\path\to\proposal-assistant-output"
```

The final output contains:

- `inventory/file_inventory.csv`
- `document_metadata/all_documents.jsonl`
- one JSON metadata file per processed document
- `review/questions_to_answer.csv`
- `folder_metadata/*.json`
- `mirror/<year>/<proposal_branch>/documents/`
- `mirror/<year>/<proposal_branch>/metadata/`
- `mirror/<year>/<proposal_branch>/folder_summary.md`
- `reports/excluded_files.csv`
- `manifests/s3_manifest.jsonl`
