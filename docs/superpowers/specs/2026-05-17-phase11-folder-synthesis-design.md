---
name: phase11-folder-synthesis
description: Design spec for Phase 11 — folder-level metadata synthesis
metadata:
  type: project
---

# Phase 11 — Folder Synthesis Design

## Architecture

`folder_builder.py` is a pure Python module following the existing module-level-functions + dataclass-result pattern used by `scanner.py` and `two_pass.py`. No Bedrock client is instantiated inside it — it receives `use_mock: bool`. When `use_mock=False`, it makes one `call_converse_with_text` call per folder for narrative summaries; when `use_mock=True`, it generates deterministic template text.

## Data flow (one proposal branch)

```
list[DocumentMetadata]  (grouped by proposal_id from MetadataStore)
         │
         ├─ _aggregate_proposal_context()   consensus voting on name/agency/program/status
         ├─ _count_docs()                   included / excluded / manual_review
         ├─ _identify_key_documents()       priority-ordered DocumentRole list
         ├─ _apply_tracker_to_folder()      match_tracker_row + override high-authority fields
         ├─ _set_readiness_flags()          ready_for_clean_set, ready_for_future_s3
         └─ _build_summaries()             template (mock) OR Bedrock call (real)
                   │
                   ▼
         FolderMetadata  → written to folder_metadata/<proposal_id>.json
         folder_summary.md → written to folder_metadata/<proposal_id>.md
                   │
                   ▼
         FolderBuildResult(proposal_id, metadata, json_path, summary_md_path)
```

## Public API

```python
build_folder_metadata(
    documents: list[DocumentMetadata],
    *,
    tracker_rows: list[TrackerRow] | None = None,
    use_mock: bool = True,
    config: RuntimeConfig | None = None,
) -> FolderMetadata

build_all_folders(
    store: MetadataStore,
    *,
    tracker_rows: list[TrackerRow] | None = None,
    use_mock: bool = True,
    config: RuntimeConfig | None = None,
) -> list[FolderBuildResult]

render_folder_summary_markdown(metadata: FolderMetadata) -> str
```

## Aggregation logic

- **consensus fields** (agency, program, status): most common non-unknown value wins; tie → unknown
- **string consensus** (canonical_proposal_name, award_status): most common non-empty non-"unknown" value; tracker overrides if matched
- **union fields** (partners, technical_focus, commercial_focus): deduplicated union across all documents
- **first-non-None** (submission_date, phase, topic_number, solicitation_number, lead_organization): first non-None wins; tracker overrides high-authority fields

## Key document selection

Priority role list (in order): `technical_volume`, `project_description`, `statement_of_work`, `commercialization_plan`, `budget`, `budget_justification`, `abstract`, `rfp`, `foa`, `award_notice`, `quad_chart`, `final_report`, `milestone_report`. For each role, the best included document is selected (prefer `include_in_clean_set=True`). Any `rag_priority=high` documents not already in the list are appended. Cap at 10.

## Readiness flags

- `ready_for_clean_set`: `included_document_count > 0` AND `open_critical_questions == 0`
- `ready_for_future_s3`: `ready_for_clean_set` AND no documents with `export_control_review` sensitivity label

## Tracker integration

Calls `match_tracker_row(proposal_branch, tracker_rows, canonical_proposal_name=...)`. On a match, overrides: `submission_date`, `selection_notification_date`, `award_date`, `status`, `award_status`, `canonical_proposal_name`. Disagreements are logged in `tracker_disagreements`.

## Mock summaries (deterministic)

```
folder_summary_short = "This folder contains {N} document(s) for the {program} proposal
  '{name}' submitted to {agency}. Status: {status}."
folder_summary_detailed = joined summary_short from included documents (up to 5)
opportunity_context_summary = joined useful_context_summary from opportunity docs
generated_response_summary = joined summary_short from generated_response docs
```

## Markdown template

Sections: proposal header block, Summary, Document Counts table, Key Documents list, Readiness, Tracker.

## CLI

`build-folders --output-root <path> [--mock-bedrock] [--tracker-path <jsonl>] [--config <yaml>]`
Resolves run_dir as the latest `run_*/` under `output_root/logs/`. Auto-discovers tracker JSONL at `run_dir/tracker/tracker_rows.jsonl`.

## Testing

`tests/test_folder_builder.py` using fake `DocumentMetadata` payloads (no disk I/O except `tmp_path` for store round-trip). Covers: count aggregation, key document priority, readiness flags, tracker overrides, markdown sections, `build_all_folders` grouping.
