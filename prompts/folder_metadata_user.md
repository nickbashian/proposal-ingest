Summarize one proposal-branch folder for an internal proposal-writing RAG system, using only the included-document summaries provided below.

Ground every statement in these document summaries; do not invent facts, numbers, dates, or outcomes. Keep opportunity/solicitation context separate from the team's generated response. Do not include salary, labor-rate, or personal information.

Proposal: {{PROPOSAL_NAME}}
Agency: {{AGENCY}}, Program: {{PROGRAM}}, Status: {{STATUS}}
Included documents ({{INCLUDED_DOC_COUNT}}):
{{INCLUDED_DOCUMENT_LINES}}

Return one JSON object with exactly these string keys and no others:

```json
{
  "folder_summary_short": "2-3 sentence overview of this proposal and its outcome.",
  "folder_summary_detailed": "3-5 paragraph summary of the technical approach, scope, and status grounded in the documents above.",
  "opportunity_context_summary": "Reusable opportunity/RFP context if any document describes it, else an empty string.",
  "generated_response_summary": "What the team proposed (technical and commercial response content), else an empty string."
}
```

Return only the JSON object: no Markdown, no code fences, no text before or after it.
