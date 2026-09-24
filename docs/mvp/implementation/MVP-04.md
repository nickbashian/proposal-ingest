# MVP-04 implementation evidence

- Date: 2026-09-24
- Base: merged `main` at `0a033ed` (MVP-03 PR #17)
- Branch: `codex/mvp-04-structured-extraction`
- Scope: immutable, structured local extraction and inspection of captured snapshots; no live tenant, paid model, classification, or publication work.

## Outcome

The application extracts bounded PDF, DOCX, PPTX, XLSX, and plain-text snapshots into versioned units. PDF units carry pages and geometry, detected tables retain rows and headers, DOCX carries section/paragraph/table cells without invented pages, PowerPoint carries slide/shape/notes locations, and spreadsheets carry sheet/cell coordinates plus formula-cache limitations. Extracted figures retain their source version, image bytes, locator, and nearby caption. Empty, scanned, malformed, encrypted, legacy, unsupported, and limit-exceeding inputs have non-success states and recovery actions. The authenticated inspector shows original parser output, neighbors, provenance, uncertainty, and historical run selection. Optional single-page local OCR and manual figure interpretation require a separate recorded source check and remain derived content.

The extraction fingerprint uses source SHA-256, parser selection, extractor/schema revision, and relevant limits. Re-extraction creates new run/unit IDs; old units and saved citation URLs stay intact. The audit command samples source versions across families using IDs and counts without exposing source text. No original source tree writes or cloud calls occur.

Hosted review follow-up keeps parser output and OCR output bounded, excludes OCR-only settings and database configuration from parser fingerprints/worker files, retries transient failures, and reactivates a reused successful run. New parser units are unclassified. Inclusion review selects only the active run, while an older inclusion event cannot create a new publication after re-extraction. Browser previews convert TIFF/BMP to bounded PNG while the original figure and hash remain accessible. The audit batches database work, counts shared versions once, and excludes extensionless paths from output.

## Acceptance

| ID | Status | Evidence |
|---|---|---|
| 04-A | Passed offline | Synthetic PDF heading/paragraph/table/caption tests verify page and geometry, negative sign, units, and row order. DOCX tests verify section/paragraph/table-cell and superscript without page numbers. PowerPoint tests verify slide text, table cells, notes, and image. XLSX tests verify sheet/cell references and an unavailable cached formula value. |
| 04-B | Passed offline | Scanned, empty, malformed, encrypted, legacy, unsupported, page-limit, spreadsheet-cell-limit, source-size, and parser-timeout fixtures never return success; reason/recovery appears in the inspector. Archive entry, inflated-size, figure-size, unit, OCR render/time, and isolated parser time limits are configured. |
| 04-C | Passed offline; real scientific check pending 08/09 | Synthetic PDF/DOCX/PPTX figures are preserved as immutable blobs with version/locator links and nearby caption. Selective figure tasks require a reviewer source check and are labeled derived. Optional local OCR is page scoped and tested with a mocked executable; no chart values are invented or broadly digitized. Real evidence-critical figure selection is pending private calibration. |
| 04-D | Passed offline | Authenticated browser test opens the collection inspector, checks table/caption text and parser provenance, views the preserved image, records a derived source-checked interpretation, and observes scanned-file recovery. The source and unit routes require collection access. |
| 04-E | Passed offline; real sampling pending 08/09 | Re-extraction and changed-revision tests preserve prior unit IDs and a saved artifact citation. Snapshot bytes and source file mtime are unchanged. Cache reuse/invalidation and an ID-only deterministic audit sample are tested. |

## Verification and limits

Local CI-equivalent gate: 499 tests passed on 2026-09-24 after the hosted review fixes. Hosted CI and CodeRabbit disposition are recorded in PR #18. Focused tests: `tests/test_mvp04_extraction.py`. The browser scenario uses only generated fictional fixtures; set `MVP04_SCREENSHOT_PATH` to a private path if a screenshot is needed. Synthetic fidelity does not establish real scientific accuracy. The audit harness will collect per-family denominators and misses at the live seed connection boundary. PDF reading order is inferred from layout geometry and exposed as uncertain; complex layouts and image-only tables may need selective review. OCR is disabled unless an operator configures a local executable, and its output never becomes a factual source unit automatically.

Migration `0008` adds extraction runs, figure assets, visual tasks, unit context/warnings, and captured source path; `0009` adds source-order ordinal; `0010` adds visual adapter provenance. Existing source, unit, decision, draft, and publication rows are retained. Back up database/object storage before applying on retained data; use isolated restore rather than destructive reversal. All fixture generation is programmatic and fictional. The two existing PDF fixtures are explicitly marked binary in `.gitattributes` so Windows Git cannot alter their approved hashes. The prototype scanner now checks hidden names relative to its source root, allowing this `.codex` worktree to pass the unchanged 473-test baseline.

No provider calls or charges were made. Owner input: no offline extraction decisions; a PyMuPDF license decision is required before non-evaluation deployment (see operations guide). Real evidence-critical figure judgments and seed-family extraction audit are batched into MVP-08/09. MVP-05 may use these units and provenance for scoped curation but must not infer missing evidence from a successful classification.
