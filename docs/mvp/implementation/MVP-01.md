# MVP-01 implementation evidence

- Date: 2026-09-22
- Base: merged `main`, `3eb9f4ddc8e9f321db187b3ac4688c65b91e8ee9` (MVP-00 PR #14)
- Branch: `codex/mvp-01-durable-foundation`
- Scope: persistent application foundation; no live adapters, deployment, or later product workflow.

## Baseline reconciliation

The worktree was clean and matched `origin/main`. MVP-00 had implemented tooling and guardrails,
but no Django models, routes, migrations, or worker existed. The original build specification was
not present; its recorded version/hash and incorporated requirements remain in the MVP overview.
The existing package and tests were retained. ADR 0001's Django 5.2/PostgreSQL/database-worker
defaults were accepted through the MVP-00 merge; no new paid infrastructure or framework change
was needed. The application adds its own settings boundary and uses process environment plus the
existing default YAML. Legacy JSONL stays behind a read-only import service.

## Acceptance evidence

| ID | Local implementation and evidence | Live verification |
|---|---|---|
| 01-A | Fresh migrations, PostgreSQL identities/FKs/unique constraints, immutable history/provenance triggers, duplicate-byte memberships, database reconnect test, process restart test | Not required for this card; deployment recovery remains MVP-08 |
| 01-B | Default-deny middleware, collection services, ownership through parent records, 20 direct-ID ownership combinations, CSRF, revocation, logout, signed mock OIDC issuer/audience/nonce/signature/expiry/state/failed/nonallowlisted cases, fail-closed production settings | Entra login pending MVP-08 |
| 01-C | Durable leases and bounded backoff/attempts, pause/resume/cancel/quota/budget states, racing claims/delivery, cancellation before delivery, stale completion fencing, forcibly killed worker and fresh process recovery | No remote side effects claimed |
| 01-D | Atomic per-attempt/global setup/month/job reservations, unknown outcome retention, late reconciliation, bounded retries, invalid-cost rejection, disabled live adapters | Real provider billing and quotas pending |
| 01-E | Database services own state; read-only idempotent legacy import retains corrections, deterministic local handler, documented Graph/Bedrock error-shape tests, application eligibility boundary | SharePoint/Bedrock/S3/Managed KB/drafting implementations belong to later cards |

Local `make check` passed: **410 tests**, Black, Ruff, codespell, mypy, secret/private-artifact
scanner, configuration validation, Django system checks, migration drift check, and Chromium smoke.
Fresh development migrations and fixture job completion also passed. Review and hosted CI
dispositions are finalized in the PR. Test suites:
`tests/test_application.py`, `tests/test_application_process.py`; operator/demo/backup instructions:
[MVP-01-OPERATIONS.md](MVP-01-OPERATIONS.md).

## Review fixes

Initial full GitHub review covered `e35c533`:
[CodeRabbit review](https://github.com/nickbashian/proposal-ingest/pull/15#pullrequestreview-5283405533).
Both Windows and hosted Linux checks passed that initial commit. The supplemental CLI review
reported ten findings (including a duplicate URL validation finding) and eight unreviewed files;
the complete GitHub review is the authoritative coverage record. Final-commit review/CI status
is recorded on PR #15 rather than inferred from the initial review.

- Fixed budget-stop lease/attempt closure with assertions for the finished attempt.
- Fixed revocation to remove the named grant and never create users/identities/collections/grants.
- Preserved and validated database `sslmode`, requiring certificate verification in production;
  added settings subprocess tests and a direct `joserfc` development dependency.
- Pinned development/CI PostgreSQL to its inspected image digest, normalized allowed hosts,
  required OIDC URL hostnames, and encoded all credential characters in test database URLs.
- Preserved membership provenance against deletion through an additive migration.
- Added immutable local byte storage and corruption/hash/key tests; observations retain bytes.
- Declined the CLI suggestion to use Playwright's OS cache: MVP-00's bootstrap and repository
  instructions deliberately use the nonsynced `.codex` cache. Explicit overrides still work.
- Additional author checks corrected documented Bedrock 408/424 unknown-outcome accounting and
  preserved the completed-call delivery stage across repeated pause/resume without redispatch.
- CodeRabbit's second review requested directory synchronization for immutable object installation.
  POSIX storage now synchronizes newly created parent entries and the installed object directory,
  including concurrent-existing-object cases. Windows remains development-only for this adapter's
  process-restart guarantee; production writes require POSIX directory synchronization.
- Supplemental Copilot findings: fixed IPv6 local login, stale success messages, existing fixture
  identity validation, and shared YAML loading through `proposal_ingest.config`. Pending delivery
  is already preserved across pause/resume; unpublished results are hidden in the job screen.
  Declined source/artifact blob equality because curated excerpts must differ from original bytes;
  the provenance test explicitly exercises that required separation.

Development database evidence: a private logical backup preceded additive migrations 0003/0004.
After restarting/recreating the PostgreSQL container with its retained volume, the database still
held one succeeded fixture job, one JobResult, and one usage reservation. The running loopback demo
returned HTTP 200 for login and HTTP 401 for the anonymous collection route.

## Remaining connections and handoff

No owner input is needed for the local architecture. Entra configuration/admin access, live source
and provider credentials, and deployment billing checks remain in the existing MVP-08 connection
session. No private source material or paid provider call was used. MVP-02 can extend this actual
application with fixture curation/publication/evidence/drafting; the MVP-01 shell deliberately only
demonstrates job processing. Nicholas reviews and merges; automatic merge is not enabled.
