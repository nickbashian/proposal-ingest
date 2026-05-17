Synthesize folder-level metadata for this proposal branch.

Proposal branch context:

```json
{{PROPOSAL_BRANCH_CONTEXT_JSON}}
```

Document metadata records:

```json
{{DOCUMENT_METADATA_JSON_ARRAY}}
```

Tracker candidate or matched metadata, if available:

```json
{{TRACKER_CONTEXT_JSON}}
```

Return strict JSON matching the folder metadata schema. Include:

- canonical proposal identity if known
- agency/program/topic information if known
- tracker disagreements
- short and detailed summaries
- separate opportunity context summary and generated-response summary
- key documents
- counts of included/excluded/manual-review documents
- open critical question count
- readiness flags

Return strict JSON only.
