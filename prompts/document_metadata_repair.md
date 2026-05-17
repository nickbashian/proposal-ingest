The previous model response was supposed to be strict JSON matching the document metadata schema, but it failed validation.

Validation error:

```text
{{VALIDATION_ERROR}}
```

Previous response:

```text
{{RAW_MODEL_RESPONSE}}
```

Correct it to this exact schema shape and exact field names:

```json
{{DOCUMENT_METADATA_TEMPLATE_JSON}}
```

Do not use alternate legacy keys. Preserve valid information from the prior response, but remap it onto the exact field names above.

Return corrected strict JSON only. Do not add Markdown. Do not add comments. Preserve all valid information from the previous response. Use `unknown` for fields that cannot be repaired confidently.
