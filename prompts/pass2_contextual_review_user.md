Re-evaluate this single document using the branch context, then return one complete document metadata JSON object and nothing else.

Use the branch context only to resolve ambiguity or fill `unknown` fields. Do not overwrite a high-confidence Pass 1 value unless the document text or a high-confidence neighbor clearly contradicts it; when you do, raise the matching confidence score and explain the change in `processing_notes`. The proposal-branch folder name is low-trust context.

Current Pass 1 metadata:

```json
{{CURRENT_PASS1_METADATA_JSON}}
```

Branch context packet:

```json
{{BRANCH_CONTEXT_JSON}}
```

Current document text or extracted representation:

```text
{{DOCUMENT_TEXT}}
```

Return a full document metadata object that uses these exact nested field names and schema-valid enum values:

```json
{{DOCUMENT_METADATA_TEMPLATE_JSON}}
```
