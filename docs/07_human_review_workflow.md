# 07 — Human Review Workflow

## Purpose

The human review loop lets the model ask only high-value questions and gives the operator a simple spreadsheet-editable interface for correcting metadata.

## Question scopes (issue #8)

Review rows come from two sources:

- **Proposal-level arbitration** (`arbitrate-questions`, see
  `docs/03_metadata_schema.md`): reconciles document-level uncertainties
  consolidated onto a proposal record into a small, budget-capped set of
  `scope: proposal` or `scope: document_family` questions. Answering one of
  these updates the canonical proposal record and every affected document at
  once, and the decision survives pipeline reruns.
- **Operational questions** generated directly by Python (for example
  PowerPoint special-processing review) — these remain `scope: document`
  and are unaffected by the arbitration budgets.

## Review philosophy

The model should not ask questions just because something is unknown. It should ask only when the answer changes downstream behavior, such as:

- include or exclude a file
- final vs draft determination
- sensitive/confidential handling
- future RAG treatment
- proposal branch identity
- tracker match ambiguity
- PowerPoint special processing

## Global review CSV

Path:

```text
processed_output/review/questions_to_answer.csv
```

Columns:

```text
question_id
run_id
proposal_id
proposal_name
scope
decision_type
document_id
affected_document_ids
source_path
proposal_branch
file_name_original
field
question
priority
suggested_options
model_guess
model_confidence
evidence_summary
why_human_input_is_needed
user_answer
answer_type
status
created_at
updated_at
applied_at
notes
```

`proposal_name`, `scope`, `decision_type`, `affected_document_ids`,
`model_confidence`, `evidence_summary`, and `why_human_input_is_needed` are
populated for proposal-level arbitration rows and left at their defaults
(`scope=document`, the rest empty) for document-scoped and operational
rows.

## Question ID stability

Question IDs should be stable across runs.

Suggested formula:

```text
question_id = "q_" + short_hash(document_id + field + normalized_question_text)
```

This prevents duplicate questions when re-running the pipeline.

## Priority levels

```text
critical
high
medium
low
```

Defaults:

- Export critical/high/medium.
- Suppress low priority unless `--include-low-priority` is used.

## Per-file question limits

- Target: 3 questions per file.
- Maximum: 5 questions per file.
- Do not count automatically generated PowerPoint questions against this limit if they are created by Python rather than AI.

## Suggested options

Where possible, provide controlled choices.

Examples:

```text
field: include_in_future_rag
suggested_options: true | false

field: version_status
suggested_options: final | draft | template | submitted_version | working_version | superseded | unknown

field: sensitivity_labels
suggested_options: public | internal | confidential | partner_confidential | financial_sensitive | export_control_review | personal_info | unknown
```


## Optional question-answering GUI

For operators who do not want to edit wide CSV rows directly, the CLI includes a small local GUI:

```bash
proposal-ingest answer-questions --output-root processed_output
```

The GUI opens `processed_output/review/questions_to_answer.csv` by default and shows one question at a time. It displays the branch/file context, field, priority, status, question text, and model guess; it provides previous/next navigation, controlled-choice buttons when `suggested_options` or a boolean `answer_type` is available, a text box for custom answers, a skip button, and an accept-suggestion button. Answers are written back to the same CSV as `status=answered`, so the existing `apply-answers` command remains the deterministic system of record for patching metadata.

## Apply answers behavior

The MVP applies answers deterministically.

Rules:

- Empty `user_answer` means no change.
- `status=skip` means do not apply.
- `status=applied` means do not reapply.
- Values must be validated against schema.
- Invalid values are written to `reports/answer_apply_errors.csv`.
- Every applied correction is archived.
- A row with `scope=proposal` or `scope=document_family` updates the
  canonical `ProposalMetadata` record and propagates to every document in
  `affected_document_ids` where the field is also carried there, and appends
  a durable `HumanOverrideRecord` to `review/human_overrides.jsonl` so a
  later `synthesize-proposals` rerun cannot silently discard the decision.
  `decision_type=authoritative_document` is special-cased: `user_answer` is
  the chosen document's `document_id`, and applying it reassigns
  `document_lineage` authority instead of patching a scalar field.

Archive path:

```text
processed_output/review/answered_questions_archive.csv
```

## Answer types

```text
boolean
enum
string
list
notes_only
```

## Manual correction examples

### Final vs draft

```csv
field,question,model_guess,user_answer
version_status,"Is this the final submitted technical volume or an earlier draft?",draft,final
```

### Budget exclusion

```csv
field,question,model_guess,user_answer
include_in_future_rag,"Should this budget file be excluded from future RAG due to salary/rate details?",false,false
```

### PowerPoint special handling

```csv
field,question,model_guess,user_answer
needs_powerpoint_processing,"No same-name PDF was found for this PowerPoint. Does it need special future processing?",unknown,yes
```

## Fields that can be patched by CSV

Document-scoped rows (`scope=document`) use these field names:

```text
canonical_proposal_name
proposal_short_name
agency
agency_subunit
program
phase
topic_number
topic_title
solicitation_number
status
award_status
document_category
document_role
origin_type
version_status
include_in_clean_set
include_in_future_rag
rag_priority
recommended_rag_treatment
sensitivity_labels
manual_review_required
manual_review_reasons
operator_notes
needs_powerpoint_processing
```

Proposal-scoped rows (`scope=proposal` or `scope=document_family`) use the
canonical field map in `human_overrides.py` (`PROPOSAL_FIELD_MAP`), keyed by
the last dotted segment of `field` — for example `award_status`,
`status`, `canonical_proposal_name`, `agency`, `program`,
`submission_date`, `award_date`, `award_amount`, `lead_organization`,
`prime_or_sub`, `partners`, `version_status`, `sensitivity_labels`,
`recommended_rag_treatment`, and `rag_priority`. Each entry declares where
the value lives on the proposal record and, where applicable, on affected
documents, so one answer can update both.

## Critical question examples

- File appears to contain salary/rate details but was marked for clean-set inclusion.
- File appears to contain PII but was marked for clean-set inclusion.
- Same proposal branch has multiple plausible final technical volumes.
- A document is high-value but ambiguous between final/draft.
- Tracker row match is ambiguous and would affect status/date/result metadata.

## Medium question examples

- Agency or program is uncertain.
- Topic number is uncertain.
- Partner confidentiality is unclear.
- PowerPoint has no PDF equivalent and might be important.

## Low question examples usually suppressed

- Minor title uncertainty.
- Missing document date when it does not affect downstream behavior.
- Unknown partner list from low-value admin file.
