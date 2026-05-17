# 09 — Testing Plan

## Testing principles

- Most tests should run without AWS.
- Use fake documents and mock Bedrock responses.
- Test pipeline state transitions, not model intelligence.
- Keep real Bedrock tests manual or opt-in.

## Test categories

### Unit tests

#### Scanner tests

- Detect year folders.
- Treat immediate child folders as proposal branches.
- Ignore stray files directly in year folders.
- Recursively scan nested proposal branch files.
- Skip hidden/system files.
- Skip temporary Office files.

#### File filter tests

- Support `.pdf`, `.docx`, `.doc`, `.xlsx`, `.xls`, `.csv`, `.txt`, `.md`.
- Inventory ZIP only.
- Ignore images.
- Mark PowerPoints inventory-only.

#### PowerPoint supersession tests

Cases:

```text
Deck.pptx + Deck.pdf -> pptx superseded_by_pdf, pdf processable
Deck.pptx only -> pptx inventory_only + question generated
Deck final.pptx + Deck.pdf -> no supersession unless same stem rule says yes
```

#### Hashing tests

- Same file contents produce same hash.
- Same content in different paths maps to same `document_id`.
- Different content maps to different `document_id`.

#### Metadata validation tests

- Valid model JSON passes Pydantic validation.
- Invalid enum fails.
- Missing required fields fail.
- `unknown` is accepted where allowed.
- Confidence fields are required for major inferred fields.

#### Question loop tests

- Generates stable question IDs.
- Suppresses low-priority questions by default.
- Enforces max questions per file.
- Applies valid CSV answers.
- Rejects invalid enum values.
- Does not reapply already-applied answers.

#### Clean set builder tests

- Copies included files.
- Does not copy excluded files.
- Sanitizes filenames.
- Handles filename collisions.
- Writes metadata next to copied files.
- Generates S3 manifest.

### Integration tests in mock mode

Test a fake source tree:

```bash
proposal-ingest run-all \
  --source-root sample_data/fake_source_root \
  --output-root tmp/test_output \
  --mock-bedrock
```

Expected outputs:

- inventory exists
- metadata exists
- questions CSV exists
- folder metadata exists
- clean set exists
- S3 manifest exists

### Manual Bedrock tests

These are not CI tests.

#### Smoke test

```bash
proposal-ingest bedrock-smoke-test
```

Expected:

- returns simple response
- logs model ID and region

#### One-file direct document test

```bash
proposal-ingest process-file --file sample_data/manual/small.pdf --output-root tmp/bedrock_test
```

Expected:

- valid JSON metadata
- raw response optionally saved
- Bedrock usage logged

#### One-file local extraction test

Use a larger or unsupported direct file path forcing extraction.

Expected:

- extracted text/summary passed to model
- metadata validates

#### One-folder test

```bash
proposal-ingest process-folder --source-folder "...\2025 DOD SBIR AF251 Li-ion" --output-root tmp/one_folder
```

Expected:

- pass 1 metadata for supported files
- low-confidence files flagged
- questions generated
- no source files modified

## Test fixtures

### Fake Technical Volume

Should contain:

- fake agency/program
- fake technical goals
- fake performance metrics
- clear final/submitted wording

Expected classification:

```text
document_category = proposal_response
document_role = technical_volume
origin_type = generated_response
version_status = final or submitted_version
include_in_clean_set = true
include_in_future_rag = true
rag_priority = high
```

### Fake Budget

Expected classification:

```text
document_category = budget_financial
document_role = budget
include_in_clean_set = false or manual_review_required
include_in_future_rag = false
sensitivity_labels includes financial_sensitive
```

### Fake FOA Instructions

Expected classification:

```text
document_category = opportunity_document
document_role = foa or submission_instructions
origin_type = source_opportunity
boilerplate_heavy = true if long compliance content
recommended_rag_treatment = summary_only or metadata_only
```

### Fake Letter of Support

Expected classification:

```text
document_category = partner_document or supporting_document
document_role = letter_of_support
sensitivity_labels includes partner_confidential unless clearly public
manual_review_required may be true
```

## Edge cases to test

- empty folder
- folder with only unsupported files
- folder with all files excluded
- duplicate documents in different subfolders
- exact duplicate final files
- final and draft versions present
- malformed model JSON
- repair prompt succeeds
- repair prompt fails
- source file deleted between scan and analysis
- output root inside source root should be rejected

## Regression tests

After every meaningful pipeline change:

```bash
make check
proposal-ingest run-all --source-root sample_data/fake_source_root --output-root tmp/test_output --mock-bedrock --force
```
