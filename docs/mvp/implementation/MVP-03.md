# MVP-03 implementation evidence

- Date: 2026-09-22
- Base: merged `main` at the start of this card
- Branch: `codex/mvp-03-source-sync`
- Scope: proposal/year source capture, offline Graph contracts, and safe legacy staging. No private corpus or live tenant was accessed.

## Outcome

The application now captures one configured proposal folder at a time through a read-only local adapter or a scoped Microsoft Graph drive item delta adapter. A `SourceSyncRun` persists its page cursor. Each observed item has a scoped disposition and path observation. Verified bytes are stored once by digest; source identity remains the provider item ID or local filesystem file ID. Each source can retain multiple proposal memberships, versions, and historical paths. A completed clean full enumeration may retire absent scope memberships; any network error, revoked access, capture race, size limit, or interrupted page leaves retirement blocked. The 2025 boundary is the selected folder under `2025`; a later-dated file in that folder remains in scope. Observation timestamps indicate capture time.

The legacy import command validates prototype inventory, metadata, and answers, reports accepted and quarantined rows in dry-run mode, and preserves exact original exports on commit. Imported answers remain historical evidence and never create an application decision or publication permission. Ambiguous partial inclusion and stale/unverified answer scope are quarantined.

## Acceptance

| ID | Status | Evidence |
|---|---|---|
| 03-A | Passed offline | Local tests enumerate folders, supported files, ZIP, email, legacy format, and administrative exclusions; a file named for 2026 within a 2025 proposal folder is captured. Every observed item has a scoped disposition. |
| 03-B | Passed offline; live pending 08 | Contract tests cover Graph paging, throttling, 410 checkpoint expiry, access failure, and interrupted crawl; local tests cover rename, move, changed bytes, duplicate content, removal, and resumption. Retirement occurs only after a completed issue-free full enumeration. Actual tenant delta behavior is pending. |
| 03-C | Passed offline | Stable item IDs survive rename/move; equal bytes share a blob while source and proposal memberships remain separate. Versions retain upstream version/ETag, blob SHA-256, and capture time. Changed-during-download is retried then recorded as inconsistent without a verified version. |
| 03-D | Passed for source work contract | Same-version reruns verify and reuse stored bytes. Stage fingerprints depend only on relevant extractor/model/prompt/schema/policy revisions. Later extraction, classification, and publication jobs consume this contract in their own cards. A failed capture stays scoped and another proposal can complete. |
| 03-E | Passed offline | Dry-run schema validation, identity mapping using path/proposal/hash, collision and answer quarantine, exact export preservation, and repeat-import idempotence have database tests. No imported value becomes an inclusion decision. |
| 03-F | Passed by offline contract; live pending 08 | Source requests are GET-only to the configured drive/root delta and item endpoints. Client-credential POST is to Entra only. Download redirects receive no Graph bearer. Tokens and signed URLs are not saved to source records, import reports, or browser payloads. Live selected-site access is pending. |

Focused MVP-03 tests: `tests/test_mvp03_sync.py`, `tests/test_mvp03_graph.py`, and `tests/test_mvp03_legacy.py`. All use synthetic bytes and blocked/mock Graph responses. The final `scripts/dev.py check` result and CodeRabbit disposition are recorded in the PR after review.

## Operator path and limits

See [MVP-03-OPERATIONS.md](MVP-03-OPERATIONS.md) and [MVP-03-LEGACY-IMPORT.md](MVP-03-LEGACY-IMPORT.md). The Graph adapter is implemented but not connected to the seed folders. Before live use, the tenant administrator must grant the separate read-only app access to the selected site, provide runtime credentials, and verify the three seed folder IDs. No full-tenant crawl is offered. Graph's scoped delta support and selected-site permission behavior require live validation in MVP-08. The current command stores source snapshots in local immutable storage; production S3 source snapshot publication is part of the later live connection work.

Migration `0006` adds scope/run/presence/capture-issue tables; `0007` adds immutable path observations. Both are additive and retain existing source/version/publication rows. Back up database and object storage before applying on retained data. To roll back a development database with no retained MVP-03 capture, stop sync and migrate to `0005`; reversing the migrations deletes new sync lineage. For retained data, restore a verified pre-migration backup into a separate database instead of reversing. To stop a connector without losing lineage, stop invoking `sync_sources`; failed/incomplete runs cannot retire sources.

There were no provider calls or charges during this card. Owner input is limited to tenant administrator read grant and seed-folder IDs at the MVP-08 live connection boundary, plus any material legacy interpretation left quarantined by a private import report. The next implementation card is MVP-04, after this PR is merged.
