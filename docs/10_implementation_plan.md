# 10 — Implementation Plan

## Build strategy

Use small, testable increments. Avoid starting with Bedrock. Build the local state machine first, then add AI calls.

## Current phase status

- Phase 0 — complete
- Phase 1 — complete
- Phase 2 — complete
- Phase 3 — complete
- Phase 4 — complete
- Phase 5 — complete
- Phase 6 — complete
- Phase 7 — complete
- Phase 8 — complete
- Phase 9 — complete
- Phase 10 — complete
- Phase 11 — complete
- Phase 12 — complete
- Phase 13 — not started

## Phase 0 — Repo bootstrap

Deliverables:

- repo structure
- `pyproject.toml`
- `.env.example`
- `.gitignore`
- Makefile
- GitHub Actions
- empty package under `src/proposal_ingest`
- simple Typer CLI with placeholder commands

Acceptance criteria:

```bash
make check
proposal-ingest --help
```

## Phase 1 — Scanner and inventory

Status: complete

Deliverables:

- source root scan
- year/proposal branch detection
- file inventory CSV/JSONL
- file hashing
- skip hidden/system/temp files
- ignore stray year files

Acceptance criteria:

```bash
proposal-ingest scan --source-root sample_data/fake_source_root --output-root tmp/output
```

Produces inventory with expected rows.

## Phase 2 — File rules and PowerPoint handling

Status: complete

Deliverables:

- supported file type classification
- ZIP inventory-only behavior
- image ignore behavior
- PowerPoint inventory-only behavior
- same-stem PDF supersession detection
- PowerPoint review question generation

Acceptance criteria:

- `.pptx` with same-stem `.pdf` is superseded.
- `.pptx` without PDF creates review question.

## Phase 3 — Metadata models and store

Status: complete

Deliverables:

- Pydantic models
- JSON/JSONL writer
- metadata store helper
- run manifest
- validation tests

Acceptance criteria:

- valid mock metadata saves
- invalid metadata fails predictably

## Phase 4 — Mock Bedrock mode

Status: complete

Deliverables:

- mock analysis function
- deterministic fake metadata
- `analyze --mock-bedrock`

Acceptance criteria:

```bash
proposal-ingest run-all --source-root sample_data/fake_source_root --output-root tmp/output --mock-bedrock
```

Produces end-to-end output without AWS.

## Phase 5 — Bedrock smoke test

Status: complete

Deliverables:

- AWS profile/region loading
- Bedrock client wrapper
- `bedrock-smoke-test`
- usage/error logging

Acceptance criteria:

```bash
proposal-ingest bedrock-smoke-test
```

Returns a short successful response.

## Phase 6 — Process one file with Bedrock

Status: complete

Deliverables:

- prompt loading
- direct DocumentBlock path
- local extraction path
- model JSON parsing
- repair prompt
- raw response debug save toggle

Acceptance criteria:

```bash
proposal-ingest process-file --file <small-pdf> --output-root tmp/file_test --save-raw-responses
```

Produces valid document metadata.

## Phase 7 — Batch document analysis

Status: complete

Deliverables:

- `analyze` command
- skip already-processed hashes
- force options
- per-file error handling
- usage logging

Acceptance criteria:

- one proposal branch processes without halting on a bad file.

## Phase 8 — Human review loop

Status: complete

Deliverables:

- global `questions_to_answer.csv`
- question ID stability
- answer application
- answer archive

Acceptance criteria:

- edit CSV manually
- rerun `apply-answers`
- metadata changes are applied and logged

## Phase 9 — Two-pass contextual analysis

Status: complete

Deliverables:

- low-confidence flagger
- branch context packet builder
- pass 2 prompt
- conservative merge logic
- pass 2 change report

Acceptance criteria:

- ambiguous fake letter improves classification after pass 2 using branch context.

## Phase 10 — Grants tracker integration

Status: complete

Deliverables:

- tracker parser
- tracker row normalization
- AI-assisted tracker matching prompt or function
- disagreement reporting

Acceptance criteria:

- fake proposal branch matches fake tracker row
- tracker dates/status override AI guesses
- disagreement logged when names differ

## Phase 11 — Folder synthesis

Status: complete

Deliverables:

- folder metadata generation
- folder summary Markdown
- key document list
- readiness flags

Acceptance criteria:

- one branch produces coherent folder metadata.

## Phase 12 — Clean set and S3 manifest

Deliverables:

- flattened document copy
- safe filename cleanup
- metadata copy
- excluded files report
- S3 manifest
- stop on critical open questions

Acceptance criteria:

- clean output contains selected files only
- excluded files are reported
- manifest rows point to expected future S3 keys

## Phase 13 — Real pilot run

Recommended real-world pilot:

1. Run `process-folder` on one known clean proposal folder.
2. Review metadata manually.
3. Run one messy folder.
4. Adjust prompts/rules.
5. Run one full year.
6. Only then run the whole archive.

## Suggested implementation chunks for AI coding agents

Do not ask Copilot to build the whole system at once. Use the following chunks:

1. repo bootstrap + CLI shell
2. scanner + inventory
3. file rules + PowerPoint logic
4. Pydantic schemas + metadata store
5. mock Bedrock mode
6. Bedrock smoke test
7. one-file analysis
8. batch analysis
9. question CSV loop
10. folder synthesis
11. clean set builder
12. tests and docs cleanup
