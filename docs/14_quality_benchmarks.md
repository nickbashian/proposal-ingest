# Quality Benchmarks and Proposal-Aware RAG Output (Issue #9)

## Purpose

Earlier phases protect schema validity and deterministic mechanics. This
phase adds an explicit, CI-safe benchmark suite that checks whether the
pipeline is actually producing a scalable knowledge base: does it select
authoritative documents, apply standing policies correctly, minimize
low-value human review, and package proposal-level context effectively for
future RAG and agent use — and does the clean-set/manifest output make the
canonical proposal record a first-class retrieval object.

## Benchmark corpus

`sample_data/quality_benchmark/` holds a small, representative set of
synthetic, non-confidential proposal branches (plain `.txt` files, so the
filename-keyword signals the mock analyzer infers from them stay easy to
read in a diff):

- **`2025/Well Documented Battery SBIR/`** — a draft and final technical
  volume, reviewer feedback, an award notice, a budget, opportunity
  boilerplate (a NOFO), an evaluation-criteria document, a support letter,
  and a byte-identical duplicate of that support letter. Exercises every
  standing knowledge-base treatment policy at once: authoritative-final vs.
  superseded-draft, budget exclusion, boilerplate-vs-evaluation-criteria
  differentiation, and duplicate-file collapse — and is expected to produce
  **zero** human review questions.
- **`2025/Sensitive Personal Info Proposal/`** — a final technical volume
  plus a biosketch document carrying personal information, which must be
  restricted from the clean-set copy and flagged in the proposal's
  sensitivity summary rather than silently dropped or silently included.

This is a deliberately small, extensible subset of the branch patterns
described in issue #9 (rejected-with-feedback, conflicting-status,
tracker-only-evidence, and genuinely-ambiguous-authority scenarios). Those
scenarios that depend on cross-document conflict resolution rather than
per-document filename signals are covered at the unit level instead — see
"Relationship to other tests" below — because the mock analyzer
intentionally infers metadata from filenames only and cannot manufacture a
believable cross-document conflict (e.g., disagreeing award status) from
filenames alone. Add more branches under `sample_data/quality_benchmark/`
as new scenarios come up; give each one a matching expected-outcome fixture
(next section) and it is automatically picked up by
`tests/test_end_to_end_quality.py` and `evaluate-quality --expected`.

## Expected-outcome fixtures

`tests/fixtures/quality_benchmark/expected/*.json` holds one machine-readable
expected-outcome file per benchmark branch, matched by `proposal_branch`
(either an explicit `proposal_branch` key in the fixture, or the filename
stem). Supported assertions:

```json
{
  "proposal_branch": "Well Documented Battery SBIR",
  "fields": { "question_count": 0, "document_count": 8 },
  "max_question_count": 0,
  "authoritative_document_roles": ["technical_volume"],
  "excluded_from_rag_document_roles": ["budget"]
}
```

- `fields` — exact-match checks against a small set of computed proposal
  fields (`status`, `award_status`, `agency`, `program`, `question_count`,
  `document_count`).
- `max_question_count` — a ceiling rather than an exact match, for branches
  where the exact count may vary by policy tuning but explosion must still
  fail the check.
- `authoritative_document_roles` — the set of `document_role` values among
  documents flagged `is_authoritative` in `document_lineage`.
- `excluded_from_rag_document_roles` — the set of `document_role` values
  among documents whose `knowledge_base_treatment.recommended_rag_treatment`
  is `exclude`.

These are intentionally structural, not exact-prose, comparisons: they hold
up unchanged whether the proposal was synthesized in mock mode or by a real
Bedrock call, which is what makes them usable for both CI and local
real-model evaluation (see below).

## Running the benchmark

```bash
# CI-safe, deterministic, no AWS calls
proposal-ingest evaluate-quality \
  --source-root sample_data/quality_benchmark \
  --output-root tmp/quality_eval \
  --mock-bedrock \
  --expected tests/fixtures/quality_benchmark/expected

# Local-only, opt-in real-model comparison against the same structural fixtures
proposal-ingest evaluate-quality \
  --source-root sample_data/quality_benchmark \
  --output-root tmp/quality_eval_real \
  --real-bedrock \
  --expected tests/fixtures/quality_benchmark/expected
```

`evaluate-quality` runs the pipeline end-to-end (scan through
`build-clean-set`), prints the run-level quality report, and — when
`--expected` is given — prints PASS/FAIL per proposal branch and exits
non-zero on any mismatch. Omit `--expected` to just run the pipeline and
inspect the generated reports by hand.

`tests/test_end_to_end_quality.py` runs the same mock-mode pipeline as part
of `pytest`/CI and asserts against both the expected-outcome fixtures (via
the shared `proposal_ingest.quality_benchmarks` comparison helpers) and the
generated artifacts directly (retrieval object schema validity, manifest
relationship fields, provenance report contents).

## Relationship to other tests

Question-arbitration nuances that depend on cross-document conflict rather
than per-document filename signals are already covered at the unit level
and are not duplicated here:

- `tests/test_question_arbiter.py::test_duplicate_document_uncertainties_yield_one_canonical_question`
  — many documents flagging the same underlying fact must consolidate into
  exactly one review question (not one per document).
- `tests/test_question_arbiter.py::test_proposal_budget_caps_questions_per_proposal`
  — the per-proposal question budget is a hard cap, so genuine question
  explosion is structurally impossible regardless of corpus size.
- `tests/test_proposal_synthesizer.py::test_document_scope_uncertainty_not_consolidated_into_unresolved_decisions`
  — a document-scoped, low-impact uncertainty (e.g. a missing optional
  field) never becomes a proposal-level question by itself.

`tests/test_end_to_end_quality.py::test_question_count_does_not_scale_with_document_count`
adds the volume angle those tests don't cover directly: a well-documented
proposal with many (20) consistent documents still produces zero questions,
demonstrating that question count tracks ambiguity, not document count.

## Proposal-aware RAG output reference

`build-clean-set` writes, per proposal, under
`mirror/<year>/<proposal_branch>/`:

| Path | Contents |
|---|---|
| `proposal_metadata.json` | Full synthesized `ProposalMetadata` record (issue #7) |
| `provenance_report.json` | Per-proposal explainability report — authoritative/downgraded/excluded documents, standing policies applied, policy exceptions, Bedrock inferences used, human overrides applied, remaining unresolved decisions |
| `retrieval/proposal_context.json` | `ProposalRetrievalRecord` — the proposal's primary RAG retrieval entry point. References documents/evidence by `document_id`; never duplicates source document text |
| `retrieval/document_manifest.jsonl` | One `DocumentManifestEntry` per document in the proposal's lineage (including excluded ones, with `local_clean_path: null`), carrying role/version/authority/treatment/sensitivity |

And at the run level:

| Path | Contents |
|---|---|
| `reports/quality_report.json` | Run-level provenance report — proposal/document counts by treatment, questions by proposal and decision type, suppressed/override-resolved counts, Bedrock calls and tokens by stage, synthesis sources |
| `manifests/s3_manifest.jsonl` | One `proposal_record` row per proposal (pointing at `retrieval/proposal_context.json`) plus one `document` row per copied document, each carrying `object_type`, `document_role`, `version_status`, `authority_rank`, `recommended_rag_treatment`, `is_authoritative`, `superseded_by_document_id`, `contains_unique_reasoning`, `sensitivity_labels`, and `parent_proposal_record` |

A downstream ingestion client can filter `manifests/s3_manifest.jsonl` for
`object_type == "proposal_record"` to enumerate proposal overviews first,
then drill into a given proposal's `document` rows (or
`retrieval/document_manifest.jsonl` directly) for authoritative or
supporting documents — without ever needing to duplicate document text
inside the proposal record itself.
