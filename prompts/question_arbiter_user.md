Decide which of the candidate proposal-level questions below genuinely need a human answer, consolidating any that represent the same underlying issue. Ground every judgment in the supplied context — do not invent agencies, dates, outcomes, partners, or figures not present in the packet.

Arbitration context packet:

```json
{{ARBITRATION_CONTEXT_JSON}}
```

Return one JSON object of this shape (omit any candidate you decide does not need a human answer; keep every field on the ones you return except `question`, `suggested_options`, and `why_human_input_is_needed`, which you may rewrite for clarity):

```json
{
  "questions": [
    {
      "question_id": "q_...",
      "question": "...",
      "suggested_options": "option_a | option_b",
      "why_human_input_is_needed": "..."
    }
  ]
}
```

Return only the JSON object: no Markdown, no code fences, no text before or after it.
