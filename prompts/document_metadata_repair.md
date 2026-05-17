A previous response was supposed to be one strict JSON object matching the document-metadata schema, but it failed validation. Your only job is to fix the structure and field names so it validates. Do not re-analyze the document, change conclusions, or invent new metadata.

Validation error:

```text
{{VALIDATION_ERROR}}
```

Previous response:

```text
{{RAW_MODEL_RESPONSE}}
```

Correct it to this exact schema shape and exact nested field names:

```json
{{DOCUMENT_METADATA_TEMPLATE_JSON}}
```

Repair rules:

- Preserve every piece of valid information from the previous response; only remap it onto the correct field names and structure.
- Do not use legacy or invented keys. Use the exact schema field names shown above.
- Every enum value must be one of the schema's allowed values, spelled exactly. If a value cannot be mapped to an allowed enum value, use `unknown`.
- Inclusion reason invariant (a frequent cause of failure): if `include_in_clean_set` or `include_in_future_rag` is `true`, `include_reason` must be a non-empty string; if both are `false`, `exclude_reason` must be a non-empty string. Derive the reason from the prior response's content rather than fabricating new facts.
- Confidence values must be numbers between 0.0 and 1.0. Date fields must be ISO `YYYY-MM-DD` strings or `null`.
- Use `unknown`, `null`, or empty values for anything that cannot be repaired confidently.

Return the corrected strict JSON object only — no Markdown, no code fences, no comments, no text before or after the object.
