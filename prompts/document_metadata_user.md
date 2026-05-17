Analyze the attached or extracted document and produce structured document metadata.

Context supplied by the pipeline:

```json
{{PIPELINE_CONTEXT_JSON}}
```

The source path and folder name may be messy and unreliable. Use them as weak clues only. Do not let folder names override document evidence.

Known global rules:

- Supported document categories include opportunity/source documents and generated proposal-response documents.
- Treat source opportunity material such as RFPs, FOAs, topic descriptions, submission instructions, evaluation criteria, DFARS clauses, and terms as contextual material. Identify useful context but avoid recommending full RAG ingestion for boilerplate-heavy documents.
- Treat generated response material such as technical volumes, project descriptions, abstracts, quad charts, commercialization plans, reports, letters, and statements of work as likely higher-value future RAG material.
- Budget spreadsheets and files containing salary/rate details should default to `include_in_future_rag=false`.
- PII-containing files should default to `include_in_future_rag=false`.
- Partner letters and partner capability statements may be useful but should be marked confidential unless clearly public.

Return JSON matching this high-level structure:

```json
{
  "schema_version": "0.1.0",
  "document_id": "...",
  "proposal_id": "...",
  "document_identity": {},
  "proposal_context": {},
  "content": {},
  "opportunity_treatment": {},
  "inclusion": {},
  "sensitivity": {},
  "tracker_matching": {},
  "confidence": {},
  "questions_for_user": [],
  "processing_notes": []
}
```

For every question in `questions_for_user`, include:

```json
{
  "field": "field_name",
  "question": "question text",
  "priority": "critical|high|medium|low",
  "suggested_options": ["option1", "option2"],
  "model_guess": "...",
  "why_it_matters": "Explain how the answer changes downstream behavior."
}
```

Return strict JSON only.
