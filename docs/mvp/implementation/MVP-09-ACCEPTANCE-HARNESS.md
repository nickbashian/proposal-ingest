# MVP-09 offline acceptance harness

This harness validates frozen acceptance manifests and scores a bounded set of alpha
criteria without database access, model access, or provider calls. It complements
the existing classifier comparison command, which remains separate. The harness does
not establish live acceptance or model quality by itself.

## Private-data boundary

Keep real labels, source/version/unit identifiers, reviewer notes, group memberships,
and HMAC fingerprints in the ignored private_evaluations/ directory. The CLI refuses
inputs or outputs outside that directory (including paths that resolve outside through
a symlink). It rejects copied source excerpts, prompts, and raw responses. Store exact
source passages in the source corpus and use source-version/unit references in the
private review process.

Family keys in reports are restricted to opaque codes such as F1, F2, and F3.
Case and leakage-group keys may identify private records, so the scorer never includes
them in the aggregate report or console output. Keep source fingerprints as
hmac-sha256:<64 lowercase hex characters> computed with a private key held outside
the manifest and repository. The HMAC lets separate private manifests detect related
content without exposing a reusable plain hash.

The version-controlled sample_data/acceptance_harness.synthetic.json is fictional
and intentionally too small to pass the real alpha gates. Its expected result is
pending, not acceptance. Use it only to smoke-test the CLI.

## Manifest lifecycle

Create a candidate manifest with:

- schema_version 1, unique suite_id, kind, source_snapshot, policy_revision,
  schema_revision, prompt_revision, and sampling_method.
- inventory_counts is an independently audited discovered-item total per opaque
  family code. A01 disposition rows must equal this count per family, so omitted
  source items fail coverage instead of disappearing from the denominator.
- kind is one of calibration, seed_frozen, expansion_held_out, or synthetic.
  Each manifest contains exactly one matching group/case split.
- groups records a private group_key, its split, and zero or more HMAC fingerprints.
  Keep a proposal and all related versions/duplicates in one leakage group.
- cases uses a unique private case_key, opaque family_key (F1 to F99), group_key,
  matching split, one supported metric (A01, A02, A04, A05, A06, A07, A08, or A19),
  and typed data. Metric-specific data fields are validated strictly; source text
  fields are not accepted.
- Private acceptance suites require frozen_by. Freeze time is added by the CLI.

Freeze an owner-reviewed candidate into a new, immutable file:

    python scripts/evaluate_acceptance.py freeze --manifest private_evaluations/candidates/seed-v1.json --output private_evaluations/frozen/seed-v1.json

Compare a candidate against earlier frozen calibration/seed manifests to reject
leakage by group key or HMAC fingerprint:

    python scripts/evaluate_acceptance.py freeze --manifest private_evaluations/candidates/expansion-v1.json --output private_evaluations/frozen/expansion-v1.json --against private_evaluations/frozen/seed-v1.json

The same --against option is available to validate and score. Use score to write a new
report under private_evaluations/; outputs are never overwritten:

    python scripts/evaluate_acceptance.py score --manifest private_evaluations/frozen/seed-v1.json --report private_evaluations/reports/seed-v1-run-001.json

Exit codes are 0 for pass, 1 for fail or invalid input, and 2 for pending sample
coverage. Console output contains only an overall state and whether the private report
was written. The aggregate JSON contains suite revision, split, metric statuses,
per-family numerator/denominator/rate, and applicable review-workload counts. It
contains no case/group/source identifiers.

Metric data fields are:

| Metric | Required fields |
|---|---|
| A01 | disposition, reason; failed/deferred also require recovery_route |
| A02 | valuable, retained, essential_conditions_preserved, critical |
| A04 | answerable, required_support_ids, top10_eligible_ids (at most ten) |
| A05 | case_kind (gap/conflict), observed (gap/conflict/answered), unsupported_claims |
| A06 | citation_resolves, semantic_support |
| A07 | critical_error, flagged |
| A08 | usefulness_rating (1–5), ordinary_editing_only |
| A19 | discovered_items, extracted_passages, supported_nonsensitive, automatically_tagged, automatically_resolved, substantive_questions, human_decisions, review_seconds, unsupported_or_failed |

Each A01 case represents one discovered item, and case counts must equal
inventory_counts per family. Each A19 family has one row, and its discovered_items
must match that independent count. The A19 denominator remains supported_nonsensitive;
automatically_tagged can include sensitive items awaiting review, so it is reported
separately and bounded by extracted_passages.

## Scored gates

| Metric | Gate and minimum evidence |
|---|---|
| A01 | Every inventory case has a recognized disposition and reason; failed/deferred cases need a recovery route. |
| A02 | At least 60 valuable passages and 20 per family; >=95% retained with essential conditions and zero critical losses. |
| A04 | At least 20 answerable queries; >=18 have all required support among the top ten eligible results. |
| A05 | At least five gap/conflict tasks; each returns the expected gap/conflict and has zero unsupported claims. |
| A06 | Every evaluated citation resolves and has manually confirmed semantic support. |
| A07 | At least 20 critical-fidelity cases; zero unflagged critical errors. |
| A08 | At least five owner-rated writing tasks; at least four score >=4/5 with ordinary editing only. |
| A19 | Three-family denominator of supported, non-sensitive passages; >=80% automatically resolved and <=10 substantive questions total. Abstentions remain in the denominator; discovered items, extracted passages, automatic tags, unsupported/failed counts, human decisions, and review time are reported separately. |

Metrics without evidence or minimum sample size are pending; they are not counted as
passed. A failed gate fails the overall report even when another metric is pending.
Per-family counts preserve denominators so pooled scores cannot conceal a weak family.
These metrics cover only the listed slices. A09/A10/A11/A12/A13/A15/A16/A17 require
their separate lifecycle, access, operations, injection, figure, and live connection
evidence in the acceptance report.

## Status and live boundary

MVP-09 remains pending until the private source labels/tasks are owner-checked, all
required metrics and lifecycle scenarios are reported, the three-family live path from
MVP-08 is verified, and Nicholas signs off on usefulness and limitations. The fictional
fixture and this offline scorer do not qualify as live evidence. Automatic clearance of
private passages remains supervised until frozen inclusion/exclusion tests and
source-checked calibration pass.

MVP-10 should reserve one additional 2025 family before tuning, freeze it as
expansion_held_out, and run --against the calibration and seed suites. Reuse the same
runner, query/pass rules, and frozen seed regression after the held-out gate. A failed
held-out set becomes validation data; do not report it again as unseen generalization.
