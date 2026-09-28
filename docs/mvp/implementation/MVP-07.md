# MVP-07 implementation evidence

Base: merged `main` at `2be89dbc3d9b986ff39950a1708bd9947836bf3b` (MVP-06, PR #22),
confirmed by fetching origin on September 28, 2026. The clean primary checkout was reused;
there were no attached worktrees or unrelated edits to preserve.

## Design and acceptance

The writing workspace uses the existing publication eligibility service. Approved voice
is read independently from current curation plans and explicit human voice approvals; it
never enters factual publication or factual citation identity. Current decisions, sources,
plans, extraction generations, source exclusions, and the restore hold apply to selection
and dispatch. The inspector can show original/context/history, while the request contains
only curated factual bytes and separately approved voice. A summary never leaks its raw
supporting passage into the model request.

Each generation saves its exact request before dispatch. Private citation URLs resolve
only through the owning session's saved packet. Requests include version/locator/hash,
decision/generation revisions, scientific labels, prompt/model/policy versions, task,
audience/length/assertions, prior revision, and separate voice context. Bedrock additionally
saves the exact Converse wire arguments. A durable attempt releases database locks during
the call and rechecks ownership, eligibility, deadline, cancellation, and session revision
on delivery. Live jobs use the existing persistent spending ledger; uncertain calls remain
charged conservatively. No tool capability is offered.

The reuse gate is conservative: unknown/unsupported quantities, chemistry/conditions,
claim-type paraphrases, citation mismatches, assertions, contradictory quantities, and
other unverified prose stay marked for review. It is not semantic scientific validation.
No generated draft or assertion becomes corpus knowledge through saving/restoring/exporting.

| ID | Status | Synthetic evidence |
|---|---|---|
| 07-A | Passed synthetic acceptance | Four-view/filter/exact-ID test; source inspector shows original, qualifiers, context, date/version, and comparable captured versions. Identifiers bypass Managed KB ranking; temporal filters use established labels. |
| 07-B | Passed synthetic acceptance | Voice permission withdrawal, exclusions, restore hold, and duplicate collapse tests. Packet/provenance retains collapsed locations. Voice quantities are absent from factual support. |
| 07-C | Passed synthetic acceptance | Exact request spy and Bedrock wire-contract test; preserved owner-private citation round-trip; numeric/chemistry/condition/claim-type checks; existing MVP-06 raw-summary exclusion regression. |
| 07-D | Passed synthetic acceptance | Contradictory fictional cycling quantities prompt a focused source/conditions question; task assertions remain labeled; explicit gaps and unsupported prose block reuse. Saving never writes corpus classifications. |
| 07-E | Passed synthetic acceptance | Intervening edits fence generation; stale edit/regeneration conflicts; restore/compare; copy and optional source appendix; source update preserves saved citations and blocks new use. |
| 07-F | Passed synthetic acceptance | Excluded and eligible prompt-injection fixtures; HTML/link escaping; two-user direct-ID/UI ownership matrix for sessions, revisions, packets, exports, generation/provider jobs and private citations; browser queued/slow/cancel/error/session-expiry tests. |

The suite deliberately distinguishes collection-shared original artifacts from owner-private
writing packets/artifacts. A second allowlisted collection member can inspect published
original evidence, but cannot inspect another writer's saved packet, revision, generation,
provider job, export, or workspace. PostgreSQL guards also reject cross-session packet and
provider-job reassignment and preserve immutable requests/revisions.

## Demonstration and owner input

`fixture_writing` prepares five fictional tasks: outline, prior-results passage, technical
section, conflicting-results comparison, and reviewer-facing revision with a proposed
experiment. It includes separate approved voice with a deliberately unsupported quantity,
an edited revision, an excluded source injection, and a source-update command that makes
saved results historical. See [MVP-07-OPERATIONS.md](MVP-07-OPERATIONS.md).

On September 28 Nicholas accepted recording the proposed real evaluation set for later
private source selection: prior-results passage; technical approach outline;
solicitation-compliance section; conflicting/versioned-result comparison; response to
reviewer feedback. Proposed voice set: opening, technical approach paragraph, transition
or closing. These are proposed real cases, not completed real evaluations.

## Verification, review, and live boundary

The documented `.venv/Scripts/python.exe scripts/dev.py check` is the canonical
`make check` fallback on this shell: `make` remained unresolved after refreshing persistent
Machine/User PATH. PostgreSQL on loopback 54329 was used; no reinstall was needed.
The final local gate passed: 610 tests, including browser, PostgreSQL ownership/immutability,
and injected provider contracts; formatting, lint, spelling, typing, secrets, configuration,
and migration-drift checks also passed. The separate synthetic mock pipeline passed. Ordinary checks and demonstration use synthetic
data and deterministic/injected adapters. No AWS/private transfer/deployment is claimed.

The Bedrock route is implemented and disabled by default, requires explicit opt-in and a
configured bounded reservation, and has an injected-client request/budget/delivery test.
Live model/account behavior, scientific fidelity, real citations, costs, Entra/SharePoint,
deployment, and usefulness remain MVP-08/09 checks. Voice terms/TypeSafe remain unchanged.
No DOCX export, autonomous submission, external chat, or product public-web search was added.
Rollback retains additive schema and immutable history while disabling generation; the
operator guide covers recovery and the publication hold. Nicholas alone merges.

## Initial review dispositions

CodeRabbit CLI 0.8.0 completed the initial full working-diff review with seven findings.
Each was checked against current behavior:

| Finding | Disposition |
|---|---|
| Client setup could leave a conservative charge without a provider call | Fixed: setup failures are known failures and release the reservation; injected failure regression. |
| Bare URLs could become active links in exported Markdown | Fixed: unverified URLs are omitted from text and source labels while server-created citation links remain intact; Markdown/text regressions. |
| Python-only defaults break older application inserts after additive migration | Fixed: matching database defaults for request, checks, and reuse status; migration drift and PostgreSQL gate. |
| Browse enriched every artifact and repeatedly queried decisions | Fixed: prefilter candidates and bound expensive enrichment; reuse prefetched decision events. Exact proposal lookup and current eligibility remain application-owned. |
| Split the milestone test module by implementation module | Deferred: organizational only; the file intentionally collects the 07-A–F acceptance scenarios. |
| Provider timeout could exceed its durable job lease | Fixed: default 90-second read timeout and startup validation leave room for the five-second connection timeout within the 120-second lease. |
| Empty configurable demonstration task set could index an empty list | Fixed: guard empty sessions and missing latest revisions. |

The local rehearsal applied migrations through 0027, created five fictional workspaces,
and verified the comparison and exact saved citation in the browser. Updating the source
preserved the original 92% excerpt and visibly marked it historical and withdrawn for new
use. Synthetic screenshots and raw CLI output stay in ignored local `tmp/`.

The CodeRabbit follow-up remains pending: automatic approval review rejected the external
code upload even after the outgoing source/fixture set and passing secrets scan were
verified. An explicit owner approval request is pending. The initial review is not claimed
as final-diff review; no review waiver or merge approval is inferred.
