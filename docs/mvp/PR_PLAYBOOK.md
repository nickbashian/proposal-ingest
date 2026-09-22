# MVP pull-request playbook

Read [the overview](README.md), [setup checklist](SETUP_AND_CONNECTIONS.md), and [acceptance matrix](ACCEPTANCE.md) together with the current PR card. MVP numbering is separate from the prototype's historical phase numbers.

## Common completion contract

Every PR must deliver working behavior for its bounded scope, appropriate regression/contract/UI tests, updated setup/operator notes, and a short implementation report. The report maps every acceptance ID to evidence and says **passed**, **failed**, or **pending live connection**. Do not call an untested live behavior complete.

After code changes, run `make check`; Phase 0 makes this usable on this Windows host and in Linux CI. Also run the PR's relevant database/browser/adapter tests. Ordinary CI uses synthetic data and blocked or mocked provider calls. Live tests require an explicit opt-in and configured budget. Run the final checks again after review fixes if the change affects them. Never fix a failing gate by weakening scientific or exclusion requirements.

Commit small, coherent steps within the PR. Include migration compatibility and rollback instructions for stateful changes. A deployment rollback must not reactivate artifacts excluded by a newer decision. Preserve user changes in the checkout. All branches use `codex/mvp-NN-short-purpose` unless the owner specifies another name.

### CodeRabbit and Nicholas gate for every PR

1. Complete the coding scope and local checks; inspect the diff for credentials, source content, generated private artifacts, and unrelated changes. At an explicitly identified owner-action boundary, the PR may carry pending live acceptance steps after all independent implementation and verification is complete. These steps remain unpassed and must be closed before claiming the corresponding live milestone.
2. Optionally run CodeRabbit locally before opening the PR. The VS Code extension can review local changes; it is an optional convenience, not a required GUI dependency for an unattended agent. The CLI can also produce agent-readable reviews. Validate the installed command/version in Phase 0. [CodeRabbit IDE](https://www.coderabbit.ai/ide), [CLI documentation](https://docs.coderabbit.ai/cli).
3. Push the branch and open the PR with acceptance evidence, demo steps, migration/rollback notes, costs, pending live checks, and a short list of requested owner decisions. Do not merge it. Attach the PR to the coding task when the environment supports that.
4. Default to CodeRabbit's GitHub PR review because findings remain with the merge record. If needed, request `@coderabbitai full review` for the initial complete diff; use `@coderabbitai review` after fixes. Inspect inline review threads, review summaries, and top-level comments, not just the check badge. [CodeRabbit review commands](https://docs.coderabbit.ai/guides/commands).
5. Triage each finding: fix a substantiated issue and add relevant regression coverage; explain an incorrect finding with evidence; explicitly defer a nonblocking improvement with an owner-visible reason. Do not blindly apply suggestions or resolve threads without verification.
6. Push fixes, rerun affected checks, and obtain review coverage for the final commit. Record reviewed commit, review link or sanitized local report, and dispositions. A local VS Code/CLI review can satisfy this gate if it covers the full proposed diff and final changes and its evidence is attached to the PR; an earlier single-commit review cannot cover later edits.
7. Present a short demo and any batched owner input. Nicholas alone merges. After his changes or a consequential rebase, repeat applicable checks/review. Begin dependent implementation from the merged base.

If review is unavailable, rate-limited, or skipped, mark it pending rather than green. Fixes and other work can continue; only Nicholas can explicitly waive that external review gate. A review timeout does not authorize merge. Pause and request a decision if review cycles expose a scope change or repeatedly disagree; do not run an unbounded automated correction loop. Suggested escalation point: three substantive cycles without convergence.

### Agent handoff template

```text
Implement MVP-NN from docs/mvp/PR_PLAYBOOK.md on the current merged main.
Read docs/mvp/README.md, SETUP_AND_CONNECTIONS.md, ACCEPTANCE.md, the supplied
product specification if available, and applicable repository instructions.
Reconcile actual code with the planning baseline before changing it.

Scope: [copy the selected PR card, including acceptance IDs].
Dependencies: [merged PRs/commit and any explicit pending connection items].
Do not build later PRs except the minimum shared contract specified here.
Preserve read-only sources, private-data boundaries, human corrections,
application-side eligibility, and the stated cost envelope.

Make routine reversible implementation choices and record them. Continue
independent work when credentials are absent; use the real application
workflow with local adapters, never a disconnected mock screen.

Deliver implementation, migrations, focused tests, demo, and operator notes.
Run make check and relevant acceptance tests. Create a PR, complete the
CodeRabbit review/fix cycle, and report evidence against every acceptance ID.
Collect my remaining input in one concise list. Do not merge the PR.
```

This is the execution instruction to give the agent later; it is not a claim that the named future commands or application modules already exist. Persist handoff state under `docs/mvp/implementation/` using sanitized reports: last completed acceptance IDs, tests, design choices, pending work, and relevant commits. Keep real evaluation artifacts in private storage.

## MVP-00 — Environment, guardrails, and repository reset

**Outcome:** A new agent can start from a clean checkout and run a trustworthy baseline without rediscovering machine setup. Dependencies: none. Suggested lead: Sol; Astra reviews roadmap/instruction conflicts.

**Components:** Reproducible Python development dependencies; Windows/Linux setup; working Make entry point; hooks and CI parity; browser testing support; `.env.example`; sanitized fixture/data layout; CodeRabbit configuration/installation diagnostics; PR template; short architecture decisions. Follow the detailed tool inventory in the setup checklist.

**Acceptance:**

- **00-A:** Preserve the baseline's behavior and obtain green `make check` from documented Windows and Linux paths. Resolve README's Python 3.12 fallback against the actual `>=3.13` package constraint; use 3.13 unless a deliberate compatibility change is justified.
- **00-B:** A fresh clone can install pinned/locked dependencies and execute the existing mock pipeline with no AWS credentials. All output is confined to its configured output root. Dependency/cache locations meet the owner's Node/OneDrive rule.
- **00-C:** Add a diagnostic/bootstrap path for Git, Python, Make, Docker, AWS CLI, GitHub CLI, chosen browser tooling, and CodeRabbit; distinguish missing executable, inactive service, and missing sign-in. Diagnose before installing; do not reinstall working tools unnecessarily.
- **00-D:** CI and local checks agree, run no paid calls, and reject committed secrets/private artifacts. Add a narrowly configured secret scanner and fixture provenance policy. Configure protected-branch/required-check instructions and turn off automatic merging for this workflow where authorized.
- **00-E:** Update conflicting AGENTS/README/GitHub phase instructions to point to the MVP roadmap while retaining source protection, tests, configuration, and mock-mode rules. Archive the old roadmap as history; do not relabel the historical pilot as complete.
- **00-F:** Demonstrate an authenticated CodeRabbit review path or record the exact owner setup action remaining. Provide the single connection checklist; no live-data access is required for the coding baseline.

**Demo/evidence:** Environment report with versions, fresh setup transcript, mock run, CI results, and review-path check. **Owner input:** GitHub/CodeRabbit sign-in or installation grant if necessary; confirm engineering defaults through the PR. **Rollback:** Tooling/configuration revert; no application data migration. **Boundary:** No application build or paid infrastructure provisioning in this PR.

## MVP-01 — Durable application and worker foundation

**Outcome:** A persistent, authenticated application can own jobs and records independently of CLI runs. Depends on 00. Suggested lead: Astra.

**Components:** Django web shell, PostgreSQL migrations, application services around the existing package, local/production settings, OIDC integration boundary, worker/outbox, provider adapters, usage reservations, audit records. Specify interfaces for source enumeration/download, extraction, classification, object storage, publication, retrieval, and drafting without implementing every live adapter yet.

**Data contracts:** Separate `SourceItem`, `SourceVersion`, `ContentBlob`, `ProposalMembership`, `VersionFamily`, `ExtractedUnit`, `Decision/DecisionEvent`, `PublicationArtifact/Generation`, `Job/Attempt`, `UsageReservation`, `DraftSession/Revision/EvidencePacket`, and evaluation records. A source item is connector + tenant/site/drive/item identity, not its filename or hash. A source version records upstream version/ETag and observed content hash/time; absent historical versions are unknown, not invented. A locator belongs to a specific version and extractor revision.

**Acceptance:**

- **01-A:** Migrations create/update a fresh database; restart preserves records. Unique constraints and foreign keys prevent duplicate identities and invalid references. Two paths containing the same bytes retain two source memberships.
- **01-B:** All corpus, job, draft, export, and artifact routes enforce server-side authentication and collection authorization. Production refuses missing auth configuration; local login shortcuts bind to loopback and cannot activate in deployment mode. Mock OIDC tests cover bad issuer/audience, failed login, logout, and a nonallowlisted user.

  Establish per-object draft ownership in the service contract. Two synthetic allowlisted users must not access each other's private sessions, revisions, evidence packets, or exports, including direct-ID read/update/regenerate/delete/export requests. Collection access alone does not grant draft ownership. MVP-07 repeats these tests on the complete routes and UI.
- **01-C:** Jobs survive process termination; leases expire safely; retries/backoff are bounded; pause, resume, cancel, and quota/budget stops are explicit. Competing workers cannot commit duplicate side effects. Cancellation prevents new work; already-issued calls are accounted for and their late results cannot publish after cancellation.
- **01-D:** Budget reservations are atomic before dispatch, reconciled after calls, and retained conservatively for unknown outcomes. Retries count toward cost. No live adapter runs without its required settings; missing credentials disable that action without breaking startup.
- **01-E:** Database-backed domain services are the authority. Legacy JSONL is read through an import boundary and never dual-written as competing state. Contract tests exercise deterministic adapters and representative documented provider error shapes.

**Demo/evidence:** Start app and worker, create a fixture job, terminate/restart the worker, inspect one consistent result and usage ledger. Show denied anonymous requests. **Owner input:** None unless the architecture choice changes cost/scope. **Rollback:** Back up before migration; document restore rather than assuming every schema change is reversible. **Boundary:** No complete production parser or retrieval service required yet.

## MVP-02 — Early end-to-end local product slice

**Outcome:** Nicholas can try the whole interaction before cloud setup or detailed parser work. Depends on 01. Suggested lead: Sol.

**Components:** Small synthetic proposal fixture; collection screen; minimal typed review decision; curated text artifact; local publication and retrieval; evidence preview; basic drafting form, revision storage, and Markdown/text export. Use the same database/services/worker that live adapters will use.

**Acceptance:**

- **02-A:** Through the web interface, import one synthetic family, inspect all item dispositions, answer one inclusion decision, publish eligible fixture passages, search, pin an evidence item, generate a deterministic draft, edit it, and export it with source links.
- **02-B:** A deliberately excluded passage is absent from both publication bytes and the saved drafting evidence packet. Voice-only content is not treated as factual support.
- **02-C:** Restart retains the decision and draft. Regeneration creates a new revision and preserves user edits. The citation opens the exact saved fixture passage and locator.
- **02-D:** The interface clearly identifies local retrieval and deterministic model output. A browser test exercises this path; unauthorized access remains denied. A second run is idempotent.

**Demo/evidence:** Reproducible browser scenario and screenshots using only synthetic content. **Owner input:** Brief interaction feedback on collection → review → evidence → writing, batched in the PR. **Rollback:** Revert UI/service addition; fixture reset is confined to development data. **Boundary:** This proves workflow integration, not live retrieval or scientific quality. Later PRs extend these screens and contracts rather than replacing a throwaway demo.

## MVP-03 — Source sync, identity, and legacy import

**Outcome:** Repeatable source capture with complete accounting and stable provenance. Depends on 02. Suggested lead: Sol, with Astra review of lifecycle edge cases.

**Components:** Read-only Microsoft Graph/SharePoint adapter; local development adapter; recursive enumerator with paging; scoped proposal/year jobs; source checkpoints; snapshot storage; legacy inventory/metadata/answer import with dry-run reports. Reuse scanner/hash helpers without retaining content-hash-as-identity assumptions.

**Acceptance:**

- **03-A:** Every recursively discovered item receives a disposition, including ZIP/email/legacy formats, administrative exclusions, and items awaiting extraction. The 2025 boundary is folder membership, allowing associated later history; record capture time rather than implying a historical 2025 snapshot.
- **03-B:** Contract tests cover pagination, rename, move, changed bytes, identical bytes at multiple locations/proposals, removed item, revoked access, throttling, expired checkpoints, and interrupted crawl. Permissions/network failure never implies deletion. An authoritative completed reconciliation or verified deletion event is required before retirement.
- **03-C:** Source identity survives rename; content cache deduplicates bytes without losing memberships. Observed version identifiers/hashes reach snapshot records. A file changed during download is retried or marked inconsistent, not recorded as a verified snapshot.
- **03-D:** Unchanged reruns reuse valid results; extractor/model/prompt/schema/policy versions invalidate only affected work. Excluding one document or failing one proposal does not prevent unrelated eligible work.
- **03-E:** Import dry-run validates old schemas, preserves original exports, maps old IDs to new identities, and reports unresolvable collisions/answers. Repeat import is idempotent. Ambiguous partial-inclusion notes are not converted into whole-document permission; stale answers require evidence/scope validation.
- **03-F:** Production Graph calls are read-only and scoped to configured locations. No credentials in source URLs or browser payloads. Local contract tests pass without a tenant connection; actual seed-folder access remains a tracked live check for 08.

**Demo/evidence:** Synthetic change/retry walkthrough and a legacy import report with accepted/quarantined counts. **Owner input:** Only unresolved legacy interpretations, if material; connection prerequisites go into the shared checklist. **Rollback:** Preserve imported lineage and original exports; disable connector and restore checkpoints/database if needed. **Boundary:** Do not fetch an entire tenant or infer DOCX/PDF equivalence from names.

## MVP-04 — Structured extraction and source inspection

**Outcome:** The application can show exactly what it extracted and what it could not read. Depends on 03. Suggested lead: Astra for contracts; Sol for format-specific implementation.

**Components:** Structured PDF/DOCX extraction; PowerPoint text/notes; tables, captions, figure references, neighboring context; explicit extraction quality states; targeted OCR/visual adapter; extraction inspector. Reuse extraction libraries where they preserve required structure.

**Acceptance:**

- **04-A:** PDF fixtures preserve page locators, headings, paragraph order, tables with units, and captions; DOCX fixtures preserve section/paragraph/table-cell locators without invented pages. PowerPoint fixtures retain slide/notes locators. Relevant spreadsheet tables retain sheet/cell references and explicit formula-value limitations.
- **04-B:** Empty, scanned, malformed, encrypted, legacy, and unsupported inputs never report successful text extraction. Show the reason and a recovery action: alternate parser, selective OCR/visual task, authorized local conversion, or deferral. Resource limits bound hostile or huge files.
- **04-C:** Preserve figure assets and precise source links. Evidence-critical figures can receive selective, budgeted interpretation with a source check and derived-content label. Other figures remain visible without invented chart values. No broad automatic digitization is required.
- **04-D:** The inspector shows original extracted text beside location/context and parser/version provenance. Targeted fixtures verify conditions such as negative signs, superscripts, units, table headers, and section boundaries; uncertainty is visible rather than silently normalized away.
- **04-E:** Re-extraction changes unit versions without corrupting saved citations. Test source-read-only behavior and cache invalidation. Build an extraction audit harness for real seed-family sampling in 08/09.

**Demo/evidence:** One PDF, DOCX, slide deck, table, and scanned/failed fixture. **Owner input:** Review only genuinely ambiguous evidence-critical figures at the later real-data calibration. **Rollback:** Previous extraction versions stay intact; reselect only verified eligible artifacts. **Boundary:** Classification cannot repair missing evidence; unsupported ZIP/email has an explicit disposition, not a mandatory new parser.

## MVP-05 — Curation, scoped review, and model evaluation

**Outcome:** Durable human decisions shape precisely which material can be reused. Depends on 04. Suggested lead: Astra. If needed, split model adapter/comparison work into 05b, keeping the total at 12 PRs.

**Components:** Independent classification dimensions; deterministic rules and prior scoped decisions; bounded cross-document reconciliation; typed decision ledger and review UI; passage treatments and dependencies; task-specific Bedrock routing; Jev adapter and comparison harness. Reuse synthesis/tracker/override concepts after validating their assumptions.

**Acceptance:**

- **05-A:** Store source role, authorship, version/status, content use, claim type, chemistry/conditions, temporal meaning, and treatment separately. Missing conditions stay unknown. Tracker/submission authority cannot establish scientific truth; filename labels cannot establish submission or authorship. Voice approval requires a distinct explicit decision.
- **05-B:** Decision keys include semantic scope, entity/version-family identity, field, and decision type. Different families do not collide. Automatic resolution stores value, rationale, evidence, resolver version, and scope; model omission is not resolution.
- **05-C:** Review supports approve/edit/defer/reject/undo; enum/section selections represent partial treatment. Show recommendation, excerpts, conflicting evidence, consequence, and affected records. Broad changes preview scope; concurrent edits detect conflict. Rejecting a recommendation leaves an unresolved decision unless an explicit alternative is chosen. Deferral does not clear a critical gate.
- **05-D:** Unchanged reruns do not ask answered questions again. Material contradictory evidence can reopen a decision while preserving its prior answer; wording or run-ID changes cannot. Undo and scoped edits invalidate dependent artifacts/caches without rewriting unrelated decisions.

  Resolution order must be explicit and tested: applicable human decisions override automated guesses; within an allowed policy, narrower scoped decisions override broader defaults. Collection-wide prohibitions remain prohibitions unless an authorized policy change explicitly changes them. Conflicting human decisions or changed applicability create a visible conflict, not silent last-write-wins behavior. Undo recomputes the effective inherited value and audit trail.
- **05-E:** Persist the uncapped unresolved set. Presentation targets at most ten substantive questions across the three seed families, except genuine critical exceptions; every critical item remains discoverable and blocks only its affected publication scope. No budget cap, LLM omission, or suppression count implies clearance.
- **05-F:** Curated output plans identify eligible source units/context, excluded units, derived summaries, and metadata-only items. Summaries link to original evidence and cannot act as verbatim voice examples. Partial selection is machine enforceable, not a free-text note on a Boolean.
- **05-G:** A shared harness compares Jev, an economical Bedrock candidate, and the existing baseline on identical bounded labeled decisions, with abstention, false-exclusion, contamination, claim-type, calibration, review burden, latency, and total-cost metrics. Synthetic adapter tests cover timeout, malformed responses, missing confidence, and unavailable credentials. Destructive exclusion uses conservative policy; no uncalibrated global confidence threshold.
- **05-H:** Record TypeSafe terms/retention/training review and the private-excerpt transfer condition in the connection checklist. Missing credentials/acceptable terms leave Jev marked incomplete and use the Bedrock baseline. Real model selection and thresholds are finalized from the private benchmark in 09, not synthetic accuracy.

**Demo/evidence:** Two version families sharing a field, a partial inclusion, scoped undo, material reopening, a hidden-by-presentation critical decision still blocking, and a synthetic model comparison. **Owner input:** Agent-proposed voice passages and drafting tasks once real data is available; any material TypeSafe term ambiguity. **Rollback:** Append compensating decision events and recompute dependencies; never delete decision history. **Boundary:** No archive-wide manual labeling or assumption that Jev must win.

## MVP-06 — Curated publication and Managed KB retrieval adapter

**Outcome:** Search receives only approved material, and indexing state is explicit. Depends on 05. Suggested lead: Astra.

**Components:** Excerpt/summary artifact builder; private S3 publisher; Managed KB adapter; metadata/mapping format; asynchronous ingestion job reconciliation; active publication membership; application eligibility gate. Preserve original snapshots outside the KB-ingested prefix.

**Acceptance:**

- **06-A:** Full/partial/summary/metadata-only/excluded treatments produce the intended bytes. Excluded text is absent from uploaded/indexed artifacts, metadata snippets, neighboring context, and model packets. Automated fixtures inspect actual payloads, not just labels.
- **06-B:** An immutable artifact maps to source version, extracted units, locator, eligibility decision revision, and generation. Derived artifacts retain source mappings. Validate metadata size/type limits and citation identity through documented contract tests; exact account limits are checked in 08.
- **06-C:** Publication stages, uploads, starts/observes ingestion, reconciles expected artifacts and failures, and activates only verified work. A local processing success cannot mark indexing successful. UI shows pending/failed and last successful publication separately.
- **06-D:** Use atomic activation per proposal (or an equally explicit smaller unit). A query records a coherent set of active proposal generations. Partial refresh does not blend incompatible versions inside a family; unaffected proposals keep serving. Removal/exclusion retires application membership immediately, even while index deletion is pending.
- **06-E:** Retrieve results must resolve through active application mappings before entering a model packet. Unknown, retired, wrong-generation, or now-excluded artifacts are rejected. Pins, cached packets, and neighboring context use the same check. Recheck before drafting dispatch and before accepting a completed draft; changes during a call mark the result stale and require refresh.
- **06-F:** Tests inject upload failure, partial indexing, ingestion timeout, retry, worker crash, duplicate delivery, deletion lag, and exclusion during drafting. Recovery converges without duplicate publication or reactivation of forbidden material. Record real service reconciliation limitations explicitly; sampling alone cannot claim exact indexed-count reconciliation.
- **06-G:** Missing AWS credentials leave production adapters implemented/contract-tested and local workflow functioning. Keep live create/sync/retrieve/delete and citation checks pending for 08. If Managed KB cannot satisfy required behavior, document the concrete limitation and propose the smallest affordable alternative for Nicholas's decision.

**Demo/evidence:** Synthetic excluded payload inspection and stale-index rejection while a replacement job fails. **Owner input:** Only service limitations or cost changes; no premature request for every AWS permission. **Rollback:** Restore an eligible previously verified generation, subject to the latest decisions; otherwise remain unavailable. **Boundary:** No unmanaged always-on vector backend or direct uncurated SharePoint-to-KB ingestion substitution.

## MVP-07 — Evidence browsing and trustworthy drafting

**Outcome:** The complete writing workflow is implemented and ready for live verification. Depends on 06. Suggested lead: Sol for UI, Astra for evidence/citation contracts.

**Components:** Natural-language search plus deterministic identifier lookup; filters and use views; version comparison/context; evidence selection; separate voice retrieval; task prompt/audience/length/current assertions; outline/passage/section/comparison/revision modes; saved revisions; copying and Markdown/text exports.

**Acceptance:**

- **07-A:** Evidence, reasoning, voice, and requirements views filter by proposal, role, chemistry, established temporal status, and use. Show original passage, date/version, locator/link, qualifications, neighboring context, and comparable versions. Exact proposal IDs work without semantic ranking.
- **07-B:** Respect pinned/excluded sources; collapse redundant versions while retaining provenance. A pin never overrides current eligibility. Evidence and approved voice references are retrieved separately; voice facts cannot become technical support through style context.
- **07-C:** Save the exact evidence packet sent to the model, with source versions, locators, decision/generation revision, and prompt/model versions. Citation IDs must resolve to that packet and preserved excerpts. Unsupported numeric claims and claim-type/chemistry/condition errors are flagged or replaced by explicit gaps before any ready-for-reuse state.
- **07-D:** Missing/conflicting support yields a focused question, conflict, or marked placeholder. User assertions and new proposals remain labeled. Promotion of an assertion into reusable knowledge requires a separate explicit action, provenance, and curation; the corpus never silently absorbs generated drafts.
- **07-E:** Regeneration preserves edits as revisions; optimistic concurrency avoids lost edits across tabs. Restore/compare revisions, copy, and export with optional source appendix. Later source changes do not break saved evidence views; retired evidence is marked historical and cannot seed new drafting without eligibility checks.
- **07-F:** Source prompt-injection fixtures cannot change policy, invoke tools, exfiltrate data, or override the user's task. Validate/escape rendered source and model text, authorized artifact access, and safe source links. UI tests cover slow calls, interrupted generation, errors, and session expiration. Two allowlisted users cannot read, modify, regenerate, delete, or export each other's private drafts or associated revisions/evidence/artifacts through direct IDs or the UI; repeat this suite before adding real users.

**Demo/evidence:** Five representative fixture writing tasks, a conflicting numeric claim, separate voice evidence, an edited revision, and a source update after a draft is saved. **Owner input:** Agree the final five real tasks and a small set of voice examples proposed by the agent. **Rollback:** Keep revision/evidence records readable; disable generation if required. **Boundary:** No DOCX export, autonomous submission, external chat integration, or public-web research.

## MVP-08 — Operations, deployment, and focused connection session

**Outcome:** All feasible implementation is complete, then one real family works through the private application. Depends on 07. Suggested lead: Astra.

**Components:** Container deployment/IaC, TLS/OIDC, scoped service roles/secrets, health/job metrics, cost display/limits, retention, backup/restore/reindex, operator guide, diagnostic commands, explicit live integration suite. Follow the ordered checklist in SETUP_AND_CONNECTIONS.md.

**Acceptance:**

- **08-A (offline):** Reproducible deployment definitions, migrations, environment templates, health checks, and teardown/rollback instructions are complete. Exercise backup/restore with synthetic data and rebuild retrieval from application/object state. Proposed alpha recovery targets: no more than 24 hours of state loss with daily backups and restore within four hours; record measured results and owner-approved exceptions.
- **08-B (offline):** Operations view shows jobs, progress, failures/retries, quota stops, estimates versus recorded usage, and spend by task. Test restart, persistent budget exhaustion, model/provider outage, and secret redaction. Detailed response logging is opt-in with retention.
- **08-C (live):** Verify account/region, service APIs, model/inference-profile access, quotas, deployment cost, credit applicability, Entra sign-in, SharePoint selected-site permissions, and one repeatable source sync. Test denial for a nonallowlisted identity and anonymous requests; secrets remain server-side and buckets private.
- **08-D (live):** Publish approved excerpts from one seed family, observe completed KB ingestion, inspect normalized retrieval/citations, draft/edit/export through the deployed UI, and repeat sync without duplicate work. Update then retire a disposable test artifact and prove stale results cannot enter a new model packet.
- **08-E (live):** Restore application state into an isolated recovery environment; restore access to snapshots, decisions, revisions, and mappings; rebuild/reconcile the index; inspect saved citations. Demonstrate cancellation/quota handling and record actual costs/limits. Destroy only disposable test infrastructure after retaining evidence.

**Demo/evidence:** Sanitized deployment report with private evidence references, capability matrix, first-family result, restore timings, cost forecast. **Owner input:** One focused session for logins, admin/site grants, budget verification, deployment endpoint, and material provider-term decisions. **Rollback:** Redeploy prior app plus verified state backup under a tested recovery procedure; disable new processing and preserve private artifacts. **Boundary:** If access is pending, report “implemented and ready to connect”; do not label the alpha live.

## MVP-09 — Three-family alpha acceptance and model calibration

**Outcome:** Nicholas can use the product against real approved seed data with measured limitations. Depends on completed live checks in 08. Suggested lead: Astra for failure analysis, Sol for bounded fixes.

**Components:** Recursive coverage audit for DOD SBIR P2 A244, DOE DE-FOA-3504, and DLA SP4701; extraction/curation audit; private labeled benchmark; task-specific routing/threshold calibration; usefulness session; fixes for acceptance failures; operator handoff. No new platform architecture unless evidence demands it.

**Acceptance:**

- **09-A:** All seed-family items have dispositions; every failed/deferred item has a reason/recovery route. Audit useful passage retention, exclusions, locators, critical figure interpretations, and source-version mappings on real files.
- **09-B:** Meet or explicitly report failure against every alpha metric in ACCEPTANCE.md: >=95% valuable-passage retention, >=18/20 retrieval tasks, >=5 insufficient-evidence tasks, all evaluated citations resolving and manually supported, zero unflagged critical scientific errors, and >=4/5 useful writing tasks.
- **09-C:** Complete scoped decision persistence/reopening tests with real reruns; report uncapped unresolved counts, surfaced decisions, and time spent reviewing. Exceeding the ten-question target calls for investigation, not hidden questions.
- **09-D:** Run the three-way classifier comparison on source-checked labels, record actual models/prompt versions/cost, select routes and thresholds, and document abstentions. If Jev remains unavailable or its terms unresolved, ship the working Bedrock path with an explicitly incomplete Jev experiment; never claim a three-way result.
- **09-E:** Nicholas signs off on usefulness and known limitations. Publish a sanitized acceptance report, connection status, recurring cost projection from observed use, and private artifact references. A failing mandatory metric prevents “live alpha verified”; an owner-approved scope change must be recorded as such, not a passed test.

**Demo/evidence:** The five owner-selected writing tasks with original sources and correction notes, plus rerun and scientific-error results. **Owner input:** Scientific spot checks and usefulness assessment; review the Jev data-handling decision if still open. **Rollback:** Keep three-family snapshot and previous eligible generations; disable an unreliable route without losing decisions. **Boundary:** No full-year run before the expansion gate.

## MVP-10 — Held-out family and full-2025 expansion

**Outcome:** Demonstrated generalization and an operable 2025 collection. Depends on 09. Suggested lead: Sol with Astra reviewing regressions and rollout decisions.

**Components:** One additional 2025 family reserved before model tuning; overlap analysis; held-out retrieval/review evaluation; year inventory/forecast; bounded sync batches; regression dashboard; team onboarding instructions without enabling new users automatically.

**Acceptance:**

- **10-A:** Verify the held-out family's related versions/duplicate passages did not leak into tuning labels; document unavoidable shared boilerplate separately. Run an equivalently defined 20-query retrieval suite, >=5 gap/conflict cases, review persistence, and valuable-passage audit on that material, plus the frozen seed regression suite.
- **10-B:** If a held-out check fails, diagnose and fix before full-year processing; disclose that the family is now validation data and reserve another untouched group when possible. Do not repeatedly tune and report the same set as unseen generalization.
- **10-C:** Produce a complete read-only year inventory and projected incremental cost from observed per-unit use, including extraction exceptions and indexing storage. Present batch limits, stop/resume policy, unresolved backlog, and the $500 setup/$100 monthly envelope check to Nicholas before the expansion run.

  This is an explicit staged PR gate: after implementation, local checks, held-out results, and the cost forecast are ready, open the draft PR with 10-D/10-E marked pending. Complete CodeRabbit review of the available code and obtain Nicholas's expansion go/no-go there. Then run approved batches, attach final validation/cost evidence, address findings, and obtain final-commit review before requesting merge. Owner approval to run batches is distinct from merge approval. If expansion is declined or over budget, retain the validated alpha and keep rollout incomplete rather than marking 10-D passed.
- **10-D:** After the gate, run proposal-scoped batches with persistent budget/quality stops and checkpoints; account for every discovered item. Eligible material publishes while unresolved scopes remain blocked. Full-year completion means all items have dispositions and eligible artifacts are reconciled; deferred unsupported items remain explicitly listed.
- **10-E:** Repeat frozen seed and expansion regressions on the published collection; demonstrate restore/reindex from its current state and report measured cost. Provide the operator guide and same-collection user-add/remove procedure with authorization tests. Unequal document permissions require separate future design.

**Demo/evidence:** Held-out report, year disposition/publication dashboard, batch/recovery history, actual versus forecast cost, and final operator handoff. **Owner input:** Held-out usefulness spot check and expansion go/no-go in the PR; Nicholas merges after results are available. **Rollback:** Pause expansion, retire failed new scopes, preserve validated seed publication and decision history. **Boundary:** Other years and per-document access control are later work.
