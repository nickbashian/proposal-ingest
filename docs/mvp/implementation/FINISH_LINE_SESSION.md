# Finish-line session: owner and agent actions

This is the agenda for the focused connection and acceptance session after the
offline MVP-08 implementation is reviewed. No live provider result, private-corpus
metric, or account cost is marked passed by an offline check. Keep credentials,
source excerpts, screenshots, account identifiers, and private evaluation labels
in the approved private stores, not in this repository or a PR comment.

Draft PRs [#24](https://github.com/nickbashian/proposal-ingest/pull/24) and
[#25](https://github.com/nickbashian/proposal-ingest/pull/25) contain independent
MVP-09 and MVP-10 offline preparation from the last merged main. Rebase and
reverify them in sequence after MVP-08 and then MVP-09 merge; their current CI
does not prove the combined final branch.

## Before the session: agent-owned preparation

- Finish the MVP-08 offline gate: deployment definition, production configuration,
  backup/restore/reindex rehearsal, operations view, connection preflight, cost
  forecast tool, synthetic integration contracts, canonical checks, and CodeRabbit
  review. Record the final commit and any unresolved review issue.
- Prepare an idle, typical, and busy cost file from
  `config/cost_forecast.example.json`. Prices, account credit eligibility, instance
  size, and quantities remain blank until the intended account and region are
  verified. Do not apply the stack before the gross forecast is within the
  approved $500 setup/$100 monthly ceilings and Nicholas approves any material
  substitution. Target $50 monthly.
- Keep automatic clearance of live private passages disabled during the first
  family. Use supervised tagging and exception review until the MVP-09 policy is
  calibrated and explicitly enabled.

## Session 1: connect one family and prove recovery (MVP-08)

| Order | Nicholas or administrator action | Agent verification and evidence |
|---|---|---|
| 1 | Refresh GitHub CLI and CodeRabbit sign-in if their current tokens remain invalid. Confirm repository visibility and review coverage. | `gh auth status`, `cr auth status`, complete review of the final diff, then attach sanitized dispositions. No paid over-limit review. |
| 2 | Select the intended AWS account, region, named SSO profile, and credit/billing view. Confirm the monthly and setup envelope. | Run `scripts/connection_preflight.py`, then explicit redacted identity/API probes. Price all cost scenarios and check the applicable credits separately from gross cost. Configure billing alerts before paid probes. |
| 3 | Approve the endpoint/DNS name, access network, host size, backup retention, and any provider-term or network-isolation decision. Provision narrowly scoped secrets and IAM, curated private S3 and Managed KB access. | Validate infrastructure and runtime roles, TLS/OIDC URLs, bucket privacy, prefix isolation, model inference profiles, quotas, KB metadata/retrieval API behavior, and deployment cost. Deploy only after the cost and capability checks pass. |
| 4 | Register the web Entra app and background read-only SharePoint app; grant the selected site/drive/folder scope and initial allowlist identity. | Confirm anonymous/nonallowlisted denial, OIDC sign-in/session expiry, Graph selected-site read and denial outside scope. Record IDs privately. |
| 5 | Identify one approved seed family and permit its bounded ingestion and drafting test within the agreed per-run cap. | Repeat source sync, extract, supervised classify, resolve critical exceptions, publish eligible bytes, reconcile KB, retrieve/cite, draft/edit/export, then update and retire a disposable artifact. Record source/version/generation counts and real spend privately. |
| 6 | Review a disposable isolated restore target and recovery point. | Restore database plus immutable objects under publication hold; check decisions, saved revisions/citations, and rebuilt index. Measure state loss and restore time against 24-hour/4-hour proposed targets. Reconcile any post-backup exclusion before clearing the hold. |

The one-family session is complete only when 08-C, 08-D, and 08-E have dated live
evidence. A missing API capability or exceeded gross cost is a decision point;
preserve the local workflow and report the limitation instead of claiming a live
alpha.

## Session 2: three-family alpha (MVP-09)

Nicholas verifies source-backed scientific labels and representative voice examples
in a private review, then rates the five agreed writing tasks. The agent inventories
all three seed families, runs the frozen retrieval/gap/citation/scientific suite,
measures passage retention and review workload, calibrates the model route and
automatic policy, and records the actual gross cost. Reserve a fourth family
before tuning. Any mandatory metric miss remains visible and blocks a “live alpha
verified” claim. Jev remains optional and disabled until the actual account-tier
terms and private-transfer decision are documented.

## Session 3: expansion gate (MVP-10)

The agent presents held-out and frozen seed results, complete read-only 2025
inventory, per-batch cost forecast, quality stops, and a draft PR with 10-D/10-E
pending. Nicholas gives a separate full-year go/no-go after seeing that evidence.
Only approved bounded batches run. Final completion requires every discovered item
to have a disposition, eligible publication reconciled, frozen regressions repeated,
and restore/reindex demonstrated on the expanded state.

## Remaining decisions to record

1. Intended AWS account/region, allowed gross spend, credits, and endpoint/network
   choice after the cost and capability evidence is available.
2. Entra/SharePoint tenant grants and initial allowlist membership.
3. Retention and backup exceptions, if the proposed recovery targets or historical
   citation retention conflict with policy.
4. Five real writing tasks, private scientific/voice adjudication, and MVP-09
   usefulness sign-off.
5. Jev private-excerpt terms, if the optional three-way experiment is wanted.
6. Held-out family spot check and the separate MVP-10 expansion go/no-go.
