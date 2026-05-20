# Phase 13 Pilot Test Status

Date: 2026-05-18

## Purpose

Phase 13 is the real-world pilot stage for the proposal ingestion pipeline. The goal is to move carefully from known-small inputs to larger archive slices before attempting the full archive.

The current pilot has validated the single-folder path and started the first full-year test on the 2024 proposal archive.

## Pilot Progress

### Completed

1. Single-folder pilot completed successfully.
   - Command path exercised: `process-folder`
   - Result: metadata was generated for one known proposal folder and reviewed enough to proceed to a larger pilot.

2. 2024-only source wrapper created.
   - Wrapper path: `tmp/pilot_2024_source`
   - The wrapper contains a `2024` junction to the real read-only archive year folder.
   - This allowed `run-all` to process only 2024 while preserving the scanner's expected parent-root/year-folder layout.

3. 2024 dry scan completed.
   - Total inventoried files: `219`
   - No dry-run outputs were written.

4. AWS SSO was refreshed.
   - Profile: `proposal-assistant`
   - Identity check succeeded for account `676096976643`.

5. Authenticated 2024 `run-all` pilot started.
   - Run directory:
     `C:\Users\nbashian\OneDrive - Empower Battery Technology\Documents\Empower Proposal Database\logs\run_20260518_152442_9c7630`
   - Source root:
     `tmp/pilot_2024_source`
   - Output root:
     `C:\Users\nbashian\OneDrive - Empower Battery Technology\Documents\Empower Proposal Database`

## 2024 Pilot Scope

The 2024 scan found:

- Total files: `219`
- Eligible for processing: `200`
- Ineligible or excluded: `19`
- Tracker rows loaded: `65`

Files by proposal branch:

| Proposal branch | Files |
|---|---:|
| 2024 Activate Fellowship Application | 12 |
| 2024 ARMY SBIR A244-P063 (AWD) | 35 |
| 2024 ARMY STTR (May) | 43 |
| 2024 DOD A24B-T006-0319 | 27 |
| 2024 NAVSEA Energy Connect | 18 |
| 2024 NSF SBIR | 57 |
| 2024 NSF-EDA ROADMAP Demonstration | 2 |
| 2024 OSU VTO Si anode (d) | 3 |
| 2024 VTO 3248 Na-ion High Power (d) | 6 |
| 2024 VTO Na-ion | 16 |

## Current Run State

The authenticated 2024 run partially completed before hitting Bedrock daily token limits.

Artifacts written so far:

- Document metadata JSON files: `55`
- Raw Bedrock responses: `55`
- Bedrock usage rows: `168`
- Successful Bedrock calls: `69`
- Failed Bedrock calls: `99`
- Successful total tokens recorded: `1,246,833`
- Folder metadata generated: `0`
- Clean-set files copied: `0`
- S3 manifest generated: no

The successful Bedrock call count is higher than the metadata file count because some documents can generate more than one call, such as pass-2 processing.

## Current Blocker

The run reached the Bedrock daily token limit:

```text
ThrottlingException: Too many tokens per day, please wait before trying again.
```

This is a manageable external quota issue, not a pipeline correctness failure.

Earlier in the session, one run also failed because AWS SSO had expired:

```text
Error when retrieving token from sso: Token has expired and refresh failed
```

That was resolved by running:

```powershell
aws sso login --profile proposal-assistant
```

The current blocker after login is the Bedrock token quota.

## Observed Issues To Track

1. Daily Bedrock token quota is too low for a full-year run with the current model and direct-upload strategy.
   - The 2024 run consumed over 1.2M successful tokens before throttling.
   - A full archive run will need quota planning, batching, lower-token prompts, model tiering, or staged execution.

2. The pipeline currently continues after repeated quota failures.
   - It records failures, but a quota-specific early stop would avoid wasting time after the daily limit is reached.

3. One legacy `.xls` file triggered local Excel extraction warnings because `openpyxl` does not support old `.xls` files.
   - File observed: `Indirect_Rate_Model-Two_Pools-FY-2023-2024-proposal-final.xls`
   - The pipeline continued by attempting Bedrock upload.

4. The interrupted 2024 run has partial metadata.
   - It should be resumed carefully, not treated as a completed Phase 13 year pilot.

## Resume Plan After Quota Reset

1. Confirm AWS SSO is still valid:

```powershell
aws sts get-caller-identity --profile proposal-assistant
```

If expired, refresh SSO:

```powershell
aws sso login --profile proposal-assistant
```

2. Resume document analysis from the existing output root.

The analyzer is intended to skip existing hash metadata unless forced, so do not use `--force`:

```powershell
.\.venv\Scripts\proposal-ingest.exe analyze `
  --output-root "C:\Users\nbashian\OneDrive - Empower Battery Technology\Documents\Empower Proposal Database"
```

3. After analysis completes, continue the downstream stages:

```powershell
.\.venv\Scripts\proposal-ingest.exe export-questions `
  --output-root "C:\Users\nbashian\OneDrive - Empower Battery Technology\Documents\Empower Proposal Database"

.\.venv\Scripts\proposal-ingest.exe build-folders `
  --output-root "C:\Users\nbashian\OneDrive - Empower Battery Technology\Documents\Empower Proposal Database"

.\.venv\Scripts\proposal-ingest.exe build-clean-set `
  --output-root "C:\Users\nbashian\OneDrive - Empower Battery Technology\Documents\Empower Proposal Database"
```

4. Review the generated `questions_to_answer.csv` before relying on clean-set outputs.

If critical questions remain open, `build-clean-set` should block by design unless explicitly overridden.

## Suggested Follow-Up Improvements

Before running the full archive, consider adding:

- Quota-aware early stop on Bedrock `ThrottlingException` messages that indicate daily token exhaustion.
- A configurable per-run document limit for real Bedrock analysis.
- Optional cheaper or smaller model routing for low-risk administrative documents.
- Better handling for legacy `.xls` files, either through `xlrd` or direct-Bedrock-only routing.

## Resume Support Added

Date: 2026-05-19

The codebase now includes a resume-specific analysis command:

```powershell
.\.venv\Scripts\proposal-ingest.exe resume-analysis `
  --output-root "C:\Users\nbashian\OneDrive - Empower Battery Technology\Documents\Empower Proposal Database"
```

The resume command reports completed vs. pending eligible documents, skips any document with existing metadata, retries pending documents that previously failed, and stops after the first Bedrock daily-token quota error instead of burning calls across the remaining inventory. Pass 2 now also skips documents already marked `processed_pass2`.

The command also supports Pass 1-only resume batches:

```powershell
.\.venv\Scripts\proposal-ingest.exe resume-analysis `
  --output-root "C:\Users\nbashian\OneDrive - Empower Battery Technology\Documents\Empower Proposal Database" `
  --skip-pass2
```

This is useful for finishing pending document metadata before running contextual Pass 2 once.

## 2026-05-19 Resume Attempt

After AWS identity validation succeeded for account `676096976643`, the 2024 run was resumed against Bedrock.

Updated run state:

- Unique eligible documents: `162`
- Document metadata JSON files: `154`
- Pending unique eligible documents: `8`
- Raw Bedrock responses: `162`
- Bedrock usage rows: `278`
- Successful Bedrock calls: `172`
- Failed Bedrock calls: `106`
- Successful total tokens recorded: `2,858,585`

The resume successfully skipped existing metadata and processed additional pending documents, then paused again on the daily token quota:

```text
ThrottlingException: Too many tokens per day, please wait before trying again.
```

Additional direct-upload validation limits were observed:

- One `.docx` exceeded Bedrock's direct document-size limit.
- Several long FOA PDFs exceeded Bedrock's 100-page direct PDF limit.

The analyzer now falls back from direct Bedrock upload to local text extraction for those validation-limit cases, so they can be retried after the quota resets without repeating direct-upload failures.

## 2026-05-20 Resume Attempt

AWS identity validation succeeded for account `676096976643`, and `resume-analysis` was run again against the same 2024 pilot run.

Updated run state:

- Unique eligible documents: `162`
- Document metadata JSON files: `161`
- Pending unique eligible documents: `1`
- Raw Bedrock responses: `162`
- Bedrock usage rows: `334`
- Successful Bedrock calls: `192`
- Failed Bedrock calls: `142`
- Successful total tokens recorded: `3,319,088`
- Processing statuses: `113` processed pass 1, `35` still needing context pass 2, `13` processed pass 2
- Folder metadata generated: `0`
- Clean-set files copied: `0`
- S3 manifest generated: no

The resume processed `7` of the `8` remaining pending documents, then halted during Pass 2 after the Bedrock daily token quota was reached again:

```text
ThrottlingException: Too many tokens per day, please wait before trying again.
```

The one remaining Pass 1 document is:

```text
2024/2024 VTO 3248 Na-ion High Power (d)/Amendment_000002_FOA_DOE-NETL-EERE-DE-FOA-0003248_Final.pdf
```

That file is a long FOA amendment PDF. Direct Bedrock upload is rejected by the 100-page PDF limit, and the local-extract fallback produced a model response whose `content.milestones` values were shaped as objects rather than strings. The normalizer has been hardened to flatten object-shaped `risks`, `milestones`, and `deliverables` into strings before schema validation, with test coverage added. Verification passed via:

```powershell
.\.venv\Scripts\python.exe -m black --check src tests
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m codespell_lib
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m pytest --basetemp tmp\pytest-basetemp-full-20260520
```

The literal `make check` command could not be run in this PowerShell environment because `make` is not installed, but the equivalent Makefile commands above passed.

## 2026-05-20 Question GUI Pilot

The question export stage was run against the current 2024 pilot metadata set despite the single low-importance pending FOA amendment document.

Question export result:

- Questions exported: `273`
- Suppressed low-priority questions: `56`
- High-priority questions: `60`
- Medium-priority questions: `213`

The local `answer-questions` GUI launched successfully against:

```text
C:\Users\nbashian\OneDrive - Empower Battery Technology\Documents\Empower Proposal Database\review\questions_to_answer.csv
```

After the first GUI review batch, CSV plumbing was validated:

- Non-empty user answers: `34`
- Rows with `status=answered`: `34`
- Rows still open: `239`
- Answered rows with empty answers: `0`
- Non-answered rows with non-empty answers: `0`

Observed GUI/question-design issue: several model-generated Boolean questions were worded as two-choice prose questions, which made the `true` / `false` buttons ambiguous. Example pattern:

```text
Should the full document be indexed for RAG, or only the topic description?
```

This question targets `inclusion.include_in_future_rag`, so `true` and `false` do not cleanly represent the human choices. In the exported question set, `48` Boolean questions contained "or" choice wording, mostly on `inclusion.include_in_future_rag`.

The prompt has been tightened for future runs: Boolean questions must explicitly ask whether the target field should be set to true and explain what true and false mean; multi-treatment questions should target an enum/text field instead of a Boolean field.

One answered row initially saved free text into a Boolean field:

```text
question_id: q_84178f020d31
field: inclusion.include_in_future_rag
answer: Only topic description (pg 37-40)
```

This was corrected deterministically before applying answers:

- `user_answer` was changed to `true`.
- The original free-text answer was preserved in `notes`.
- A CSV backup was written at `review/questions_to_answer.pre_bool_note_fix_20260520_1229.csv`.
- Re-check result: `0` invalid Boolean answers among answered rows.

Planned GUI update after more pilot review:

1. For Boolean fields, prevent arbitrary free-text from becoming `user_answer`.
   - The answer value should be chosen from `true` / `false` controls only.
   - Existing `Accept suggestion` behavior should still work, but only if the suggestion is parseable as Boolean.

2. Add or clarify a separate reviewer note field in the GUI.
   - Free-text nuance should be saved to `notes`, not to the typed answer value for Boolean fields.
   - Example: `include_in_future_rag=true`, with note `Only topic description pages 37-40`.

3. Add pre-apply validation feedback in the GUI or CLI.
   - Detect invalid answers by field type before `apply-answers`.
   - Show a concise list of blocking rows with question ID, field, and invalid answer.

4. Consider changing Boolean question display text.
   - For Boolean rows, show labels such as `Set include_in_future_rag to true` and `Set include_in_future_rag to false`.
   - Keep the generated question visible, but make the actual patch value unmistakable.

Schema/question-design refinement needed after the current GUI review pass:

- Review whether `include_in_future_rag` is too coarse for opportunity documents and boilerplate-heavy source documents.
- Consider adding a field for RAG scope, such as `rag_scope_notes`, `included_page_ranges`, or an enum/value that captures partial extraction.
- Consider extending `recommended_rag_treatment` or adding a companion field to represent `full_document`, `summary_only`, `metadata_only`, `exclude`, and `partial_extract`.
- Tune prompts so multi-treatment questions target the right field rather than forcing nuanced decisions into Boolean fields.
- Use additional patterns found during the remaining GUI review before deciding on the final schema change.

## Phase 13 Status

Current status: in progress.

The pipeline has moved beyond single-folder validation and into the full-year 2024 pilot. The year pilot is nearly through document analysis, with `161/162` eligible documents complete, but it is still paused due to Bedrock daily token limits. Continue after the quota resets by retrying the final Pass 1 document, then finish Pass 2, export questions, and review metadata quality before attempting the whole archive.
