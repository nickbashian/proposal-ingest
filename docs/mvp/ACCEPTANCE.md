# Acceptance, evaluations, and evidence of completion

This document translates the supplied specification into release evidence. [PR_PLAYBOOK.md](PR_PLAYBOOK.md) defines the per-PR acceptance IDs; those local gates complement these product gates. Passing synthetic tests is necessary and does not establish model quality or live integration.

## Readiness states

| State | Required evidence |
|---|---|
| Development baseline ready | MVP-00 setup/checks reproducible; external sign-in gaps listed |
| Local product slice working | MVP-02 complete workflow through production application services using labeled local adapters |
| Implemented and ready to connect | MVP-00–07 acceptance complete, plus MVP-08 offline deployment, diagnostics, and recovery implementation; all missing live checks listed |
| Live alpha verified | MVP-08 live checks and MVP-09 real three-family acceptance passed, with Nicholas's usefulness sign-off |
| Full-2025 rollout complete | MVP-10 held-out gate passed, year items accounted for, eligible publication reconciled, regressions/cost/recovery reported |

Jev may remain an explicitly incomplete optional experiment while the Bedrock path passes alpha; missing live SharePoint/Managed KB operation cannot be treated the same way. The three-way comparison is reported as incomplete until actually performed. A changed product requirement requires an owner-recorded decision rather than editing a metric until it passes.

## Traceability and release matrix

| ID | Requirement and acceptance evidence | Build PRs | Live verification |
|---|---|---|---|
| A01 | 100% of recursively discovered seed items have processed/excluded/deferred/failed/awaiting-decision disposition, reason, and visible coverage; empty extraction never succeeds | 03, 04 | 08, 09 |
| A02 | At least 95% of manually labeled valuable passages survive curation with essential conditions; report numerator/denominator, source versions, and per-family misses | 04–06 | 09, 10 |
| A03 | Zero explicitly excluded content enters drafting context in targeted cases, including partial files, summaries, neighbors, pins, cached packets, and stale index results | 02, 05–07 | 08, 09 |
| A04 | >=18 of 20 agreed answerable tasks retrieve relevant support in top 10 eligible displayed results; include exact IDs, cross-document support, and historical reasoning | 06, 07 | 09, 10 |
| A05 | At least five unanswerable/conflicting tasks produce explicit gaps/conflicts instead of invented evidence | 07 | 09, 10 |
| A06 | Every citation in evaluated drafts resolves to its source version and passage; source checks confirm semantic support, not only a valid URL | 04, 06, 07 | 08, 09 |
| A07 | Zero unflagged target/model-to-measurement conversions, chemistry swaps, or unsupported numeric claims in the curated acceptance suite; preserve units and experimental conditions | 05, 07 | 09, 10 |
| A08 | Nicholas rates >=4 of five representative drafting tasks useful with ordinary editing; preserve revisions and copy/text/Markdown export | 02, 07 | 09 |
| A09 | Unchanged reruns ask no already-resolved decision again; scope propagation, undo, deferral, rejection, semantic identities, and evidence-backed reopening tested | 05 | 09, 10 |
| A10 | Changed, renamed, moved, deleted, excluded, and duplicate sources handled; incomplete crawls never imply deletion; inactive artifacts never support new generation | 03, 06, 07 | 08, 09 |
| A11 | Interrupt/restart jobs without duplicate decisions/invalid publication; restore database/snapshots and rebuild index; retained drafts still show historical citations | 01, 06, 08 | 08, 10 |
| A12 | Anonymous/nonallowlisted users cannot access protected routes; two allowlisted users cannot access each other's private draft objects or read/update/regenerate/delete/export operations, including direct-ID evidence/artifact access; credentials remain server-side; local auth cannot activate deployed | 01, 07, 08 | 08, 09; repeat before onboarding |
| A13 | Provider error/quota/budget exhaustion degrades visibly and predictably, retries/spend bounded across restarts, progress/cost available in UI | 01, 05, 08 | 08, 09 |
| A14 | Reserve additional 2025 family with duplicate/related-version grouping before tuning; repeat retrieval/review checks and seed regressions before full-year expansion | 05 harness, 10 rollout | 09 reservation, 10 |
| A15 | Source prompts cannot override application policy; separate evidence/voice/requirements uses; user assertions/drafts do not silently become collection evidence | 05, 07 | 09 |
| A16 | Selective evidence-critical figure interpretation source-checked, other figures preserved; unsupported content explicit with recovery route | 04 | 09 |
| A17 | Repeatable live SharePoint → curated S3 → Managed KB → authenticated writing workflow; current successful publication distinguished from local processing | 03, 06–08 | 08, 09 |
| A18 | Compare bounded classification routes, calibrate abstention/exclusion, report false exclusion/contamination/error/review load/latency/cost; Jev absence explicit | 05 | 09 |

## Evaluation design before model tuning

Maintain separate suites: deterministic software-contract fixtures, private real-corpus calibration labels, frozen seed acceptance cases, and an untouched expansion family. The agent drafts candidate cases and labels from source excerpts; Nicholas verifies material scientific/voice judgments and five writing tasks in a short session, not by labeling the archive. Store hashes, versions, locators, sampling method, expected support, and adjudication history.

Proposed initial sampling default: at least **60 valuable passages**, approximately 20 from each seed family, selected across final/draft reasoning, feedback, requirements, tables, and technical claims. Exclude no hard cases merely to raise the score. Record genuinely unavailable categories and exact per-family denominators. At 60 passages, 57 retained with their essential conditions meets 95%; any critical scientific loss still requires correction under A07. This small sample is an engineering gate, not a statistical claim about all future documents.

Prepare at least 20 explicit exclusion/partial-inclusion adversarial cases across software fixtures, plus real-source spot checks. Test leakage into derived summaries and indirect context, not just search titles. Put synthetic evidence into public fixtures; keep all real passages and draft outputs private.

For classification, begin with roughly 60–100 source-checked bounded decisions spanning useful roles, treatments, claim types, and abstention cases. Use a separate frozen acceptance subset; group proposals, versions, and duplicates so equivalent content cannot cross train/calibration/evaluation boundaries. With few families, report limitations and refrain from claiming broad calibration certainty. Evaluate rare destructive-exclusion errors separately from average accuracy and choose conservative exclusion/abstain rules. Count escalation and retry cost in every route.

The existing baseline uses different prompt/schema assumptions; explicitly map its outputs to comparable bounded labels, or declare a comparison unsupported. Use identical excerpts/tasks for supported comparisons. Missing confidence triggers a defined abstain/escalate policy rather than an accidental default. Record confusion counts and confidence-bin outcomes; do not select thresholds solely from aggregate agreement with another model.

The 20 retrieval queries should contain exact opportunity identifiers, multiple-document reasoning, version distinctions, scientific conditions, and historical ideas. Freeze query wording, eligible supporting passages, and pass rules before tuning final evaluation. Score after application filtering/deduplication; invisible stale results cannot count. For questions requiring several facts, define whether all essential supporting passages must be in the first ten. Record raw and eligible result counts to diagnose attrition.

Use at least five separate gap/conflict cases and five representative writing tasks. The tasks should cover approach outline, measured-versus-target evidence, concept-paper adaptation, historical idea recovery, and cross-proposal framing (or owner-chosen equivalents). Check all citations and substantive quantitative statements in those evaluated drafts. Repeat the fixed generation suite after substantive model/prompt/routing changes and record settings and variance; a cherry-picked run is not an acceptance result. Suggested default: three recorded runs for the gap/conflict and scientific-fidelity cases.

## Required lifecycle scenarios

Tests must cover: source rename without byte change; content change with old draft citation; same bytes in two proposals; partial Graph listing failure; permission revocation without deletion inference; stale delta token; extraction version change; two version families sharing a review field; question wording change; conflicting new evidence; deferred critical question; review cap hiding a still-unresolved item; concurrent review edits; exclusion while a draft is in flight; cached packet/pin after retirement; partial ingestion; worker crash after external success but before database acknowledgement; competing job claims; uncertain paid-call timeout; monthly budget persistence; revoked user session; backup restored while KB still contains a newer generation.

For restore, the application must reject KB artifacts it cannot map to restored active state, then reconcile/reindex deliberately. A restored database must not silently erase newer exclusions: retain/replay the durable decision audit or keep publication disabled until reconciling changes after the recovery point. Record the tested recovery point and any state loss explicitly.

## What belongs in a PR report

Provide the commit, acceptance IDs with pass/fail/pending evidence, exact test commands/results, sanitized UI demo, migration/rollback notes, CodeRabbit review commit and finding dispositions, owner decisions, known limitations, and next PR handoff. Where evidence contains private text, link a private artifact ID/location and publish aggregate counts only. Do not paste model prompts with private excerpts into GitHub or CodeRabbit context.

Live reports also record source snapshot/generation, actual provider/model identifiers, prompt/schema/policy versions, run IDs, budget cap, token/request totals, estimated/gross/credit-adjusted cost, service errors, label counts, and manual-review corrections. Outstanding exceptions are named and owned. A passing CI badge alone never constitutes these reports.
