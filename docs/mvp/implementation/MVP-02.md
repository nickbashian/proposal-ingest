# MVP-02 implementation evidence

- Date: 2026-09-22
- Base: merged `main`, `4280d35040bbfcb3f14dda4c1acadf79c64390b6` (MVP-01 PR #15)
- Branch: `codex/mvp-02-local-product-slice`
- Scope: synthetic local workflow only; no live corpus, provider, or deployment connection.

## Outcome and design

The authenticated application now demonstrates fixture import, typed inclusion review, physical
curation, local publication and factual retrieval, evidence pinning, deterministic drafting,
immutable revision history, exact citation opening, and Markdown/text export. Fixture import runs
through the existing durable job, reservation, adapter, and transactional outbox path. Other
actions use the database-backed services and provider-neutral retrieval/drafting contracts rather
than a disconnected demo state.

The synthetic family contains a measured-result passage awaiting review, a deliberately excluded
commercial passage, and an included voice-only passage. Publication copies only reviewed included
text into immutable curated blobs. Application filtering prevents excluded, inactive, or
voice-only artifacts from entering factual search, pins, or saved evidence packets. No paid call
or external connection occurs.

## Acceptance evidence

| ID | Status | Local implementation and evidence |
|---|---|---|
| 02-A | passed | Real Chromium path imports through a separate worker, shows all dispositions, records inclusion, publishes, searches, pins, generates, edits, and downloads both export forms with source links. |
| 02-B | passed | Service assertions inspect stored publication bytes and evidence-packet JSON: the explicit exclusion marker is absent; voice text may be published for voice use but is absent from factual retrieval, pins, and packets. A direct voice pin returns not found. |
| 02-C | passed | A fresh Python process reads the committed decision/draft/packet; edit and regeneration create immutable revisions 1–3 and preserve the user sentence. The citation page shows the exact passage, source-version ID, and `section Results, paragraph 2`. |
| 02-D | passed | Pages label local deterministic retrieval/drafting; anonymous collection/writing access is denied, another collection member receives not found for the owner's workspace, and repeat import/publication reuses the same job/generation without duplicate sources. |

Focused verification passed with **82 tests** across `test_application.py`,
`test_application_process.py`, and `test_mvp02.py`, covering the complete existing application
regression set plus the new service, fresh-process, management-command, authorization, and browser
paths. The CI-equivalent `scripts/dev.py check` passed **424 tests** plus Black, Ruff, codespell,
mypy, secret/private-artifact scanning, configuration validation, Django checks, migration drift,
and Chromium smoke. Literal `make check` was unavailable after the documented Windows PATH refresh,
so the repository-documented equivalent was used. A full-page synthetic browser screenshot was
inspected at ignored private artifact `private_screenshots/mvp02-workspace.png`; it is not committed
or attached to public review.

## Migration, cost, and limits

Migration `0005_local_product_slice` is additive and has an explicit development reverse path, but
its reversal deletes new workflow fields/pins; retained environments should restore a verified
pre-migration backup into a separate database. Publication is local immutable storage only, so
there is no remote rollback or stale index to reconcile. All adapters report zero provider calls
and zero cost.

This card proves workflow integration with one small synthetic family. It does not claim detailed
office-file extraction, live source sync/retrieval, model quality, or scientific usefulness. Those
remain bounded to MVP-03 onward. The next card extends the current source identity and job
contracts with read-only local/Graph sync and legacy import; it should not replace these screens.

## Review and owner boundary

CodeRabbit completed two deep full-diff local reviews and began a third final pass. Nine findings
were substantiated and fixed with regression coverage: regeneration evidence/request handling,
invalid/revoked delivery termination, source-version decision scope, correctable human decisions
with immediate stale-artifact invalidation, local-only fixture enforcement, both browser export
formats, plain-text conflict responses, accurate evidence wording, and withdrawn-citation display.
The third pass continued heartbeating without completion after its one finding was fixed and was
stopped rather than starting an unbounded review loop. Final-commit hosted review remains active on
PR #16.

GitHub Copilot's initial review added five substantiated defense-in-depth findings. The follow-up
commit enforces local-only fixture behavior at adapter selection, execution, and outbox delivery;
fails malformed delivery containers closed; binds each inclusion event and publication to one
reviewed source version; and rejects attempts to recast voice-policy content as factual. Focused
tests cover all five dispositions. Final hosted rereview status is recorded on PR #16.

CodeRabbit's hosted review added five substantiated findings. The follow-up serializes inclusion
corrections with publication on the proposal row, removes internal evidence markers and makes
downloaded citation URLs absolute, centralizes browser-cache setup, preserves malformed marker
text during regeneration, and fails unexpected fixture-delivery exceptions closed without storing
raw error details. Focused regression coverage exercises each correction; final hosted rereview
status is recorded on PR #16.

Owner input is limited to brief interaction feedback on collection → review → evidence → writing.
No credentials or connection action is needed. Nicholas merges manually after reviewing the demo;
MVP-03 begins only from merged `main`.
