Synthesize one canonical proposal record from the context packet below. Ground every statement in the supplied document metadata, extracted text, and tracker data — do not invent agencies, dates, outcomes, partners, or figures not present in the packet.

Proposal context packet:

```json
{{PROPOSAL_CONTEXT_JSON}}
```

Return one JSON object matching exactly this shape (fill in every field; use the packet's `documents` list for every `document_id`, and use null/empty defaults only when the packet gives no evidence):

```json
{{PROPOSAL_METADATA_TEMPLATE_JSON}}
```

Return only the JSON object: no Markdown, no code fences, no text before or after it.
