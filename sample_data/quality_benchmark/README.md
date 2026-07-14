Synthetic, non-confidential proposal branches used by the end-to-end quality
benchmark suite (`tests/test_end_to_end_quality.py`) and the
`proposal-ingest evaluate-quality` CLI command. Real proposal documents must
NEVER be placed here or committed to version control.

Unlike `fake_source_root/` (minimal binary PDF/DOCX/XLSX/PPTX fixtures used
for scanner/extractor/format checks), everything here is plain `.txt` so the
content — and therefore the filename-keyword signals the mock analyzer
infers from it (draft/final/superseded, budget/personal-info sensitivity,
opportunity-boilerplate vs. evaluation-criteria) — stays easy to read and
diff in a pull request.

Branches:

- `2025/Well Documented Battery SBIR/` — a draft + final technical volume,
  reviewer feedback, an award notice, a budget, opportunity boilerplate
  (NOFO), evaluation criteria, a support letter, and a byte-identical
  duplicate of that support letter. Expected to produce zero human review
  questions and to exercise every standing knowledge-base treatment policy
  (authoritative-final, superseded-draft, budget-excluded,
  boilerplate-vs-evaluation-criteria, duplicate collapse).
- `2025/Sensitive Personal Info Proposal/` — a final technical volume plus a
  biosketch document carrying personal information, which should be
  restricted from the clean set and flagged in the proposal's sensitivity
  summary rather than copied.

Expected outcomes for these branches are recorded as machine-readable
fixtures under `tests/fixtures/quality_benchmark/expected/`; see
`docs/14_quality_benchmarks.md` for the fixture format and how to add more
benchmark branches.
