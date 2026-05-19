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

## Phase 13 Status

Current status: in progress.

The pipeline has moved beyond single-folder validation and into the full-year 2024 pilot. The year pilot is partially complete and paused due to Bedrock daily token limits. Continue after the quota resets, then review metadata quality before attempting the whole archive.
