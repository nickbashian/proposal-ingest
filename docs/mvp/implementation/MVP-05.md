# MVP-05 implementation evidence

- Date: September 24, 2026
- Base: merged `main` at `ca119ec` (MVP-04 PR #18)
- Branch: `codex/mvp-05-scoped-curation`
- Coding model: GPT-6 Astra
- Scope: classification facts, persistent scoped review, eligibility plans, and bounded model comparison. No private corpus connection, paid calls, S3 publication, or Managed KB indexing.

## Decisions and behavior

Classification facts are separate per dimension and preserve origin, rationale, evidence unit IDs, resolver revision, and a stable fingerprint. The deterministic rule path uses explicit extracted support markers and never infers submission or authorship from a file name. Cross-document reconciliation compares a configured maximum of eight versions and 40 facts that share a semantic entity key; contradictions become critical review issues, not silent scientific truth. Tracker/submission metadata is not treated as a scientific claim.

Decision identity remains family + semantic scope (`family`, `entity`, `version`, `section`, or `unit`) + field + decision type. The existing family/scope uniqueness constraint keeps similarly named fields in different version families separate. Recommendations carry material evidence fingerprints; wording/run changes do not reopen, while contradictory material does. Every answer, deferral, rejection, undo, and automatic resolution is an immutable `DecisionEvent`. Effective values apply human answers before automated answers, then narrower scope within the same authority. A collection sensitivity prohibition still wins. A stale form fails instead of overwriting concurrent work.

Curated plans use active extraction runs and list selected eligible units, excluded units, explicitly approved voice units, derived summaries with original unit links, and metadata-only state. Plans are eligibility contracts for MVP-06, not yet external publication artifacts. The existing local fixture publisher honors a current plan when curation has begun and cannot bypass an invalidated plan. A change retires affected local artifacts without deleting historical citations.

The comparison harness consumes the same ordered, source-labeled cases across Jev, an economical Bedrock candidate, and the configured baseline; it records errors and abstentions explicitly. The public synthetic fixture only tests metrics and adapter behavior. The economical route has no selected inference profile, and Jev private transfer remains disabled pending effective account terms and owner decision. Actual model quality, calibration, and thresholds require the private 60–100 decision benchmark in MVP-09. The prior CLI baseline's historical prompt/schema outputs are not claimed comparable; this harness compares the configured baseline model on the new bounded task.

## Acceptance evidence

| ID | Status | Evidence |
|---|---|---|
| 05-A | Passed offline | Independent `ClassificationFact` dimensions, null unknown chemistry/conditions, conservative deterministic rule, explicit human voice approval; tests cover filename non-authority and independent fields. Real scientific classification pending private calibration. |
| 05-B | Passed offline | Family/scope/field/type key, source-validated scopes and evidence, immutable automatic event with rationale/evidence/resolver revision; two-family, precedence, and semantic-entity tests. |
| 05-C | Passed offline | Authenticated queue/detail browser flow, typed treatment/selected-unit form, approve/edit/defer/reject/undo, revision 409, evidence and impact preview. Full real-source usability feedback pending owner review. |
| 05-D | Passed offline | Material fingerprint, unchanged recommendation rerun, contradictory reopen, immutable prior answer, scoped invalidation, effective inherited value after undo. |
| 05-E | Passed offline | All unresolved rows persist; default display cap ten, full-list link, critical count and unit-specific blocking; 11-critical fixture tests hidden item. Real three-family question burden is unmeasured. |
| 05-F | Passed offline as plan contract | Partial source-unit IDs, conservative unknown/excluded paths, policy prohibition, voice separation, source-linked summary; fixture tests inspect plan lists. Physical external artifact bytes are MVP-06. |
| 05-G | Passed synthetic contracts; live comparison pending 09 | Same-case three-route fixture and adapter tests cover timeout/unavailable/malformed/missing confidence, metrics, split guard, budget stop, and conservative exclusion review. Economical model and Jev account are unconfigured. |
| 05-H | Pending owner/account terms for private Jev transfer | September 24 review in `SETUP_AND_CONNECTIONS.md`: public no-training statement, open retention and confidential-input/account agreement ambiguity, DPA/subprocessors pointer. Jev disabled and baseline retained. |

## Verification and handoff

Focused acceptance test: `tests/test_mvp05_curation.py` passed 23 tests locally under an isolated SQLite override; the browser case uses only fictional content. `sample_data/application_slice/curation_eval.json` is fictional and cannot establish real quality. Hosted CI run [156](https://github.com/nickbashian/proposal-ingest/actions/runs/36038891505) passed canonical checks, the mock pipeline, and all 519 tests against PostgreSQL and Chromium before the latest review fixes. The local canonical command passed static checks but could not connect to PostgreSQL because this Codex shell cannot access Docker Desktop's Linux engine; its database portion is not locally passed. The final-head hosted result is tracked on PR [#19](https://github.com/nickbashian/proposal-ingest/pull/19).

GitHub's additional automated review raised five material findings about plan invalidation, automatic conflict clearing, Jev transfer gating, publication bypass, and fabricated entity scopes; commit `5c8f39a` fixed them with regression coverage, and each thread was replied to and closed. CodeRabbit's initial full review on `254c45b` found five behavior/operability issues and one organizational suggestion. The behavior issues concern noncritical reopened conflicts, plan concurrency, plan query volume, enum input handling, and command errors; this follow-up implements fixes and tests. Its incremental pass also found a three-way equal-rank human conflict, now covered by regression. The organizational test-file split is deferred because this integrated acceptance suite covers one MVP card, repository instructions do not require one file per module, and splitting adds no functional evidence. Final CodeRabbit disposition and reviewed head are tracked in the PR.

No live provider calls or charges occurred. The only owner decision needed before private Jev transfer is the effective account-tier confidentiality/retention/deletion/training/subprocessor terms and whether those terms permit selected confidential excerpts. Proposed real voice examples and writing tasks are batched for MVP-09. MVP-06 may consume `CurationPlan` and must still implement physical excerpt generation, external index reconciliation, and stale-result filtering.

Migration and rollback procedures are in `MVP-05-OPERATIONS.md`. No destructive reverse migration is suitable for retained data; preserve the decision event history and later exclusions.
