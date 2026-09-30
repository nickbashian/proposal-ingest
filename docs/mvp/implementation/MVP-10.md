# MVP-10 implementation and expansion record

Base: merged `main` at `2a6d6d3` (MVP-07). This branch prepares read-only
year-inventory and bounded cost/batch planning. It does not authorize or run the
full-year expansion. The offline planner is documented in
[MVP-10-OFFLINE-PLAN.md](MVP-10-OFFLINE-PLAN.md).

| ID | Current status | Evidence required to close |
|---|---|---|
| 10-A | Pending held-out validation | Reserve a fourth 2025 family before tuning, check related-version/duplicate leakage, run the equivalent retrieval/gap/review/retention suite, and rerun frozen seed regression. |
| 10-B | Pending failure handling | Diagnose any held-out failure before expansion; disclose reuse as validation data and reserve another untouched group when possible. |
| 10-C | Offline planning mechanism prepared; real evidence pending | Complete read-only 2025 inventory, observed per-batch/gross cost forecast, checkpoint and stop rules, and separate Nicholas go/no-go. |
| 10-D | Pending explicit expansion approval | Execute only owner-approved bounded batches, then reconcile every discovered item and eligible publication. |
| 10-E | Pending expanded-state verification | Repeat frozen regressions, cost and restoration/reindex checks, and deliver operator/user-add/remove guidance with authorization tests. |

Offline evidence: the isolated full repository gate passed 636 tests; the
planner's synthetic tests, Black, Ruff, mypy, and diff checks passed. No source
bytes, database records, SharePoint, or AWS services were touched. CodeRabbit
review and required CI remain pending on the final PR head.

Rollback: discard a proposed inventory/report and rerun a read-only inventory.
No application state or publication is changed by this branch.
