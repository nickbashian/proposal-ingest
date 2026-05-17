# 03 — Metadata Schema

This document describes the intended metadata model. The implementation should use Pydantic models as the authoritative validation layer and may export JSON Schema for docs/tests.

## Design principles

- Prefer `unknown` over unsupported guessing.
- Include confidence scores for major inferred fields.
- Keep file/system metadata separate from AI-derived metadata.
- Preserve original source paths but do not expose absolute paths in future S3 metadata unless needed.
- Separate `include_in_clean_set` from `include_in_future_rag`.
- Treat RFP/opportunity context differently from generated proposal-response content.
- Make sensitivity and review requirements explicit.

## Document metadata object

### System fields

| Field | Type | Source | Notes |
|---|---:|---|---|
| `schema_version` | string | system | Example: `0.1.0` |
| `document_id` | string | system | Stable hash-based ID |
| `proposal_id` | string | system | Stable proposal branch ID |
| `run_id` | string | system | Processing run ID |
| `source_path` | string | system | Absolute source path; local only |
| `relative_path` | string | system | Relative to source root |
| `year_folder` | string | system | From folder structure |
| `proposal_branch` | string | system | Source branch folder name |
| `file_name_original` | string | system | Original filename |
| `file_name_safe` | string | system | Safe copy filename |
| `extension` | string | system | Lowercase extension |
| `size_bytes` | integer | system | File size |
| `modified_time` | string | system | ISO timestamp |
| `sha256` | string | system | Content hash |
| `processing_strategy` | enum | system | Direct, local extraction, inventory only, etc. |
| `processing_status` | enum | system | Current state |

### Document identity fields

| Field | Type | Notes |
|---|---:|---|
| `canonical_document_title` | string | AI/human |
| `document_category` | enum | Broad category |
| `document_role` | enum | Specific role |
| `origin_type` | enum | Source opportunity vs generated response, etc. |
| `version_status` | enum | `final`, `draft`, `template`, `unknown`, etc. |
| `draft_or_final_evidence` | string | Why the model thinks draft/final |
| `language` | string | Usually English |
| `document_date` | string/null | Date if identified |

### Proposal context fields

| Field | Type | Notes |
|---|---:|---|
| `canonical_proposal_name` | string | Do not rely on folder name alone |
| `proposal_short_name` | string | Optional shorter name |
| `agency` | enum/string | Normalized where possible |
| `agency_subunit` | string | e.g., Army, Navy, Air Force, ARPA-E |
| `program` | enum/string | SBIR, STTR, FOA, BAA, etc. |
| `phase` | string | Phase I, Phase II, concept paper, etc. |
| `topic_number` | string | e.g., AF251 |
| `topic_title` | string | If known |
| `solicitation_number` | string | If known |
| `submission_date` | string/null | Tracker is high authority |
| `response_date` | string/null | Tracker is high authority |
| `status` | enum | Pipeline-normalized status |
| `award_status` | enum | award/pending/rejected/etc. |
| `award_amount` | number/null | If available |
| `lead_organization` | string | Empower, OSU, partner, etc. |
| `prime_or_sub` | enum | prime/sub/unknown |
| `partners` | array | Organizations mentioned |
| `customer_or_sponsor` | string | Sponsor/customer |

### Content fields

| Field | Type | Notes |
|---|---:|---|
| `summary_short` | string | 1–3 sentence summary |
| `summary_detailed` | string | Longer structured summary |
| `primary_topics` | array[string] | Main subject areas |
| `technical_keywords` | array[string] | Useful retrieval tags |
| `technologies` | array[string] | e.g., glass anode, LFP, sodium-ion |
| `applications` | array[string] | EVs, UAS, MHD trucks, etc. |
| `performance_metrics` | array[object] | Numeric claims/targets |
| `technical_claims` | array[object] | Claims with support level |
| `risks` | array[string] | Technical/commercial risks |
| `milestones` | array[string] | Project milestones |
| `deliverables` | array[string] | Deliverables if present |

### Opportunity/RFP treatment fields

| Field | Type | Notes |
|---|---:|---|
| `opportunity_context_useful` | boolean | Useful context for future proposal writing |
| `boilerplate_heavy` | boolean | Long compliance/legal content dominates |
| `useful_context_summary` | string | Short summary of relevant opportunity context |
| `boilerplate_summary` | string | What was excluded/deemphasized |
| `recommended_rag_treatment` | enum | `full_document`, `summary_only`, `metadata_only`, `exclude` |

### Inclusion fields

| Field | Type | Notes |
|---|---:|---|
| `include_in_clean_set` | boolean | Whether to copy into clean output |
| `include_in_future_rag` | boolean | Whether future ingestion should include it |
| `rag_priority` | enum | high/medium/low/exclude |
| `include_reason` | string | Required if included |
| `exclude_reason` | string | Required if excluded |
| `recommended_chunking_strategy` | enum | future-facing |

### Sensitivity and review fields

| Field | Type | Notes |
|---|---:|---|
| `sensitivity_labels` | array[enum] | public/internal/confidential/etc. |
| `contains_budget_or_rates` | boolean | Exclude from RAG by default |
| `contains_personal_info` | boolean | Exclude from RAG by default |
| `contains_partner_confidential` | boolean | Manual review |
| `contains_export_control_flags` | boolean | Future-proof flag |
| `manual_review_required` | boolean | Required before clean-set copy for flagged categories |
| `manual_review_reasons` | array[string] | Why review is needed |

### Tracker matching fields

| Field | Type | Notes |
|---|---:|---|
| `tracker_match_status` | enum | matched/unmatched/ambiguous/not_attempted |
| `tracker_row_id` | string/null | Stable row identifier |
| `tracker_match_confidence` | number | 0–1 |
| `tracker_disagreements` | array[object] | Fields where tracker and AI differ |

### Confidence and questions

| Field | Type | Notes |
|---|---:|---|
| `confidence` | object | Per-field confidence scores |
| `questions_for_user` | array[object] | Suppressed low-priority questions not emitted |
| `fields_needing_review` | array[string] | Important uncertain fields |

## Controlled values

### `document_category`

```text
opportunity_document
proposal_response
supporting_document
budget_financial
administrative_compliance
partner_document
technical_data
report_or_deliverable
presentation
internal_planning
correspondence
unknown
```

### `document_role`

```text
technical_volume
project_description
commercialization_plan
statement_of_work
budget
budget_justification
quad_chart
abstract
letter_of_support
facilities_document
biosketch
data_management_plan
current_pending_support
rfp
foa
topic_description
submission_instructions
terms_and_conditions
dfars_clauses
evaluation_criteria
award_notice
review_feedback
milestone_report
final_report
tracker
unknown
```

### `origin_type`

```text
source_opportunity
generated_response
post_submission_feedback
award
internal_reference
unknown
```

Note: the value previously described as `award_execution` is intentionally shortened to `award`.

### `version_status`

```text
final
draft
template
submitted_version
working_version
superseded
unknown
```

### `agency`

```text
DOE
DOD
NSF
NASA
ARPA-E
Army
Navy
Air Force
DARPA
Ohio Third Frontier
Private
Other
unknown
```

### `program`

```text
SBIR
STTR
FOA
BAA
Prize
Fellowship
Accelerator
Commercial Proposal
Internal Planning
Other
unknown
```

### `status`

```text
drafted
submitted
selected
awarded
rejected
pending
not_submitted
active
completed
unknown
```

### `sensitivity_labels`

```text
public
internal
confidential
partner_confidential
financial_sensitive
export_control_review
personal_info
unknown
```

### `recommended_rag_treatment`

```text
full_document
summary_only
metadata_only
exclude
manual_review
```

## Folder metadata object

Folder metadata is synthesized after document-level metadata exists.

Core fields:

- `proposal_id`
- `schema_version`
- `year_folder`
- `proposal_branch`
- `canonical_proposal_name`
- `proposal_short_name`
- `agency`
- `agency_subunit`
- `program`
- `phase`
- `topic_number`
- `topic_title`
- `solicitation_number`
- `submission_date`
- `selection_notification_date`
- `award_date`
- `status`
- `award_status`
- `lead_organization`
- `prime_or_sub`
- `partners`
- `technical_focus`
- `commercial_focus`
- `folder_summary_short`
- `folder_summary_detailed`
- `opportunity_context_summary`
- `generated_response_summary`
- `key_documents`
- `included_document_count`
- `excluded_document_count`
- `manual_review_count`
- `open_critical_questions`
- `ready_for_clean_set`
- `ready_for_future_s3`
- `tracker_match_status`
- `tracker_disagreements`

## Inclusion logic defaults

By default:

- `include_in_clean_set` and `include_in_future_rag` match.
- They can be flipped independently.
- Budget/rate/PII files default to `include_in_future_rag = false`.
- Partner documents can be summarized and marked confidential unless clearly public.
- Boilerplate-heavy opportunity documents default to `summary_only` or `metadata_only`.
- Final versions supersede drafts when both exist and the final is confidently identified.

## Claim and metric schema

Technical claims should be structured enough for later evidence extraction.

```json
{
  "claim": "The glass anode enables fast charging while reducing lithium plating risk.",
  "claim_type": "performance",
  "support_level": "document_claim",
  "evidence_text_summary": "The document states this in the technical approach section.",
  "needs_verification": true,
  "confidence": 0.78
}
```

Performance metrics should preserve units and context.

```json
{
  "metric_name": "cycle life",
  "value": "1000",
  "unit": "cycles",
  "condition": ">80% capacity retention",
  "demonstrated_or_target": "demonstrated",
  "confidence": 0.82
}
```
