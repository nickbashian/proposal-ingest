Analyze the document provided (attached file or extracted text below) and produce one structured document-metadata JSON object.

Context supplied by the pipeline (weak hints only — the path and folder name may be messy and unreliable; never let them override document evidence):

```json
{{PIPELINE_CONTEXT_JSON}}
```

## Classification guidance

- Opportunity/source material — RFPs, FOAs, BAAs, topic descriptions, submission instructions, evaluation criteria, DFARS clauses, terms and conditions: classify as opportunity context. Capture genuinely reusable parts in `useful_context_summary`; if it is dominated by legal/compliance/formatting boilerplate, set `boilerplate_heavy=true` and recommend `summary_only` or `metadata_only` instead of `full_document`. Do not over-weight long boilerplate documents relative to concise response documents.
- Generated response material — technical volumes, project descriptions, SOWs, abstracts, quad charts, commercialization plans, reports, letters of support, biosketches: this is usually the highest-value future-RAG content.
- Budget/cost/rate spreadsheets: set `contains_budget_or_rates=true` and default `include_in_future_rag=false`.
- Files with personal information: set `contains_personal_info=true` and default `include_in_future_rag=false`.
- Partner/teaming documents: set `contains_partner_confidential=true` and mark `partner_confidential` unless clearly public.
- `include_in_clean_set` and `include_in_future_rag` are independent. Provide `include_reason` if either is true; provide `exclude_reason` if both are false.

## Output shape

Return JSON using exactly these nested field names. Pipeline-managed fields (`schema_version`, `document_id`, `proposal_id`, `run_id`, `system`) may be echoed as shown or omitted; the pipeline overwrites them. Every other field must use these exact schema names — do not invent alternate keys such as `document_type`, `citation_id`, `chunk_strategy`, `contains_pii`, or `contains_proprietary_technical`.

```json
{{DOCUMENT_METADATA_TEMPLATE_JSON}}
```

## Allowed enum values (use these exact strings; pick `unknown` when unsure)

- `document_identity.document_category`: `opportunity_document`, `proposal_response`, `supporting_document`, `budget_financial`, `administrative_compliance`, `partner_document`, `technical_data`, `report_or_deliverable`, `presentation`, `internal_planning`, `correspondence`, `unknown`
- `document_identity.document_role`: `technical_volume`, `project_description`, `commercialization_plan`, `statement_of_work`, `budget`, `budget_justification`, `quad_chart`, `abstract`, `letter_of_support`, `facilities_document`, `biosketch`, `data_management_plan`, `current_pending_support`, `rfp`, `foa`, `topic_description`, `submission_instructions`, `terms_and_conditions`, `dfars_clauses`, `evaluation_criteria`, `award_notice`, `review_feedback`, `milestone_report`, `final_report`, `tracker`, `unknown`
- `document_identity.origin_type`: `source_opportunity`, `generated_response`, `post_submission_feedback`, `award`, `internal_reference`, `unknown`
- `document_identity.version_status`: `final`, `draft`, `template`, `submitted_version`, `working_version`, `superseded`, `unknown`
- `proposal_context.agency`: `DOE`, `DOD`, `NSF`, `NASA`, `ARPA-E`, `Army`, `Navy`, `Air Force`, `DARPA`, `Ohio Third Frontier`, `Private`, `Other`, `unknown`
- `proposal_context.program`: `SBIR`, `STTR`, `FOA`, `BAA`, `Prize`, `Fellowship`, `Accelerator`, `Commercial Proposal`, `Internal Planning`, `Other`, `unknown`
- `proposal_context.status`: `drafted`, `submitted`, `selected`, `awarded`, `rejected`, `pending`, `not_submitted`, `active`, `completed`, `unknown`
- `proposal_context.prime_or_sub`: `prime`, `sub`, `unknown`
- `opportunity_treatment.recommended_rag_treatment`: `full_document`, `summary_only`, `metadata_only`, `exclude`, `manual_review`
- `inclusion.rag_priority`: `high`, `medium`, `low`, `exclude`
- `sensitivity.sensitivity_labels` (list, choose any that apply): `public`, `internal`, `confidential`, `partner_confidential`, `financial_sensitive`, `export_control_review`, `personal_info`, `unknown`

Confidence scores are floats from 0.0 to 1.0. `document_date`, `submission_date`, and `response_date` should be ISO `YYYY-MM-DD` strings or `null`. Only add items to `performance_metrics` / `technical_claims` when the document states them; each metric needs `metric_name`, `value`, and `confidence`, and each claim needs `claim`, `claim_type`, `support_level`, and `confidence`.

## Questions for the user

Only ask questions whose answers change downstream behavior. Aim for 3, never exceed 5.

`suggested_options` must be a JSON array of strings and `model_guess` must be a string — even for yes/no or numeric answers (use `"true"`/`"false"`, never JSON booleans or numbers). When the `field` is a boolean schema field (for example `inclusion.include_in_future_rag` or `sensitivity.manual_review_required`), use exactly `["true", "false"]` as the options and a `"true"`/`"false"` string as the guess. When the `field` is an enum, the options must be values from that field's allowed list above.

Each item in `questions_for_user` must use this shape:

```json
{
  "field": "schema_field_name_the_answer_updates",
  "question": "Specific question for the human reviewer.",
  "priority": "critical | high | medium | low",
  "suggested_options": ["option1", "option2"],
  "model_guess": "your best answer now",
  "answer_type": "enum | boolean | list | text",
  "notes": "Why this matters: how the answer changes inclusion, classification, or sensitivity."
}
```

Return strict JSON only.
