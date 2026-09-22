# Proposal Knowledge Base: implementation plan

Planning baseline: September 22, 2026. Repository: `nickbashian/proposal-ingest`, commit `4143a328aef2ee773806b0f17d7f7da375adac9c`.

**Recommendation: 11 sequential pull requests, numbered MVP-00 through MVP-10.** Phase 0 establishes a reproducible development environment. MVP-02 demonstrates the complete local workflow. MVP-08 connects and deploys the implemented application. MVP-09 verifies the three-family alpha. MVP-10 validates expansion and processes the remaining 2025 collection in bounded batches.

This page began as the planning delivery; MVP-00 implementation evidence is now recorded in `implementation/MVP-00.md`. It does not grant permission to provision services. The supplied *Empower Proposal Knowledge Base — Build Specification*, version 0.2, is the product requirements input. Its embedded instructions and reported owner decisions are incorporated as planning constraints; they did not trigger provider uploads, account changes, or deployment during planning. Keep the original document with the owner's private project records; do not copy private corpus material into this repository.

Requirements source: `Empower_Proposal_Knowledge_Base_Build_Spec.md`, SHA-256 `563309f2da9eb8a259868066b070f6dac8d95418970efae850d5f9884aebc8cc`. This hash identifies the version used for planning; recheck requirements if the owner supplies a revision.

## Start here

1. Read this overview and [the PR playbook](PR_PLAYBOOK.md).
2. Execute MVP-00 using [the setup and connection checklist](SETUP_AND_CONNECTIONS.md).
3. Give an implementation agent one PR card and the [handoff template](PR_PLAYBOOK.md#agent-handoff-template).
4. At each boundary, complete the CodeRabbit review cycle, demonstrate the result, and let Nicholas merge. Start the next PR from the merged result.
5. Track completion against [the acceptance and evaluation matrix](ACCEPTANCE.md). Read [the independent planning review](PLAN_REVIEW.md) before beginning.

## Delivery map

| PR | Outcome Nicholas can inspect | Main dependency | Relative size |
|---|---|---|---|
| MVP-00 | Fresh-clone setup, working checks, review tooling, accurate agent instructions | None | Small |
| MVP-01 | Durable application state, authenticated shell, resumable jobs, adapter contracts | 00 | Large |
| MVP-02 | Fixture ingestion → review → publication → evidence → editable draft → export | 01 | Medium |
| MVP-03 | Repeatable read-only SharePoint/local sync and safe legacy import | 02 | Medium |
| MVP-04 | Inspectable passages, tables, figures, locators, and extraction failures | 03 | Large |
| MVP-05 | Scientific classifications, persistent scoped decisions, model comparison harness | 04 | Large |
| MVP-06 | Eligible excerpts published to S3/Managed KB with safe generation changes | 05 | Large |
| MVP-07 | Complete evidence browser and drafting workspace with citation checks | 06 | Large |
| MVP-08 | Deployment, recovery, connections, and one real family working end to end | 07 | Large |
| MVP-09 | Measured and owner-accepted alpha across all three seed families | 08 live connection | Medium/large |
| MVP-10 | Held-out validation and resumable expansion to the full 2025 collection | 09 | Medium/large |

Sizes express integration risk and review scope, not promises about agent hours. A large PR may require several focused agent sessions and internal commits. Preserve these product boundaries rather than treating a PR as one enormous prompt. If MVP-05 becomes unwieldy, split out model adapters/comparison into MVP-05b: **12 PRs total**, with decision-ledger work still preceding publication. Avoid compressing the publication, citation, or recovery boundaries merely to reach ten PRs.

Missing credentials do not block MVP-00 through MVP-07 or the offline deployment/recovery work in MVP-08. Live-dependent criteria remain pending; they are never counted as passed by mocks. MVP-08 can be merged as **implemented and ready to connect** if Nicholas accepts that explicit status. Keep its live checklist open, and close it before claiming MVP-09 complete. MVP-09's harness and documentation can progress independently while connections are pending.

## What the existing repository contributes

The current source and tests were inspected and the baseline was executed locally. Python 3.13.13 ran **296 passing tests**. Black, Ruff, codespell, and mypy also passed. GNU Make is missing from PATH, so the Makefile's component checks were run directly; literal `make check` was not run. No AWS, SharePoint, or TypeSafe integration was tested. Git, GitHub CLI, AWS CLI, Docker CLI, and Node are present; installation does not establish authentication, a running Docker engine, or account permissions.

| Existing code | Reuse judgment and required change |
|---|---|
| `scanner.py`, `hashing.py`, `file_filters.py`, `powerpoints.py` | Reuse traversal/hash/rule mechanics. Separate source identity from content hash; preserve duplicate locations and use evidence for counterpart relationships. |
| `schemas.py`, `config.py`, `model_output.py`, `mock_bedrock.py` | Reuse typed validation, normalization, configuration, deterministic tests. Introduce explicit application schema/migrations and task-specific provider configuration. |
| `analyzer.py`, `bedrock_client.py`, `two_pass.py` | Reuse processing and quota/fallback knowledge. Move orchestration into persistent jobs; version cache keys and bound all paid work. |
| `tracker.py`, `proposal_synthesizer.py`, `folder_builder.py` | Reuse proposal context and provenance; tracker authority applies to administrative fields, never scientific truth. |
| `human_overrides.py`, `question_loop.py`, `question_arbiter.py` | Reuse scoped correction concepts and tests; replace file-based authority with a transactional decision ledger and web review. Current question caps must not become resolution or publication clearance. |
| `extractors.py` | PDF/DOCX/text helpers are starting points. Current flattened strings lose locators; DOCX extraction uses paragraphs only, and errors/unsupported formats can return empty text. Structured extraction must replace that contract. |
| `clean_set_builder.py`, `s3_manifest.py`, `retrieval_builder.py` | Export and provenance exist. `clean_set_builder.py` copies source files; a treatment label cannot implement partial exclusion. Build physical curated excerpts and explicit index publication state. |
| Existing tests and `quality_benchmarks.py` | Retain regression coverage. Filename-driven synthetic benchmarks establish mechanics, not real retrieval, scientific fidelity, or drafting usefulness. |

`AGENTS.md` incorrectly describes old Phase 12 as a stub. The README and code show Phase 12, proposal synthesis, arbitration, and quality-output work already implemented. The old 2024 pilot is a separate historical effort; finishing it is not a prerequisite for this 2025 product. Phase 0 will reconcile `AGENTS.md`, `.github/instructions/pipeline-phase.instructions.md`, README, and the old roadmap without erasing useful history. Preserve unrelated working-tree files, including the existing untracked `-A8.git`.

## Engineering defaults

These are recommended starting decisions, not additional product requirements. Record any replacement and its effect on cost, deployment, and acceptance criteria in a short architecture decision record during MVP-00/01.

- **Application:** Python 3.13, Django with templates and small amounts of JavaScript for the dedicated interface. Keep the reusable `proposal_ingest` package behind application services. Django supplies the ORM, migrations, session machinery, forms, and administration; the end-user workflow still needs its own screens. This is an engineering choice to reduce integration work for a small team. [Django overview](https://docs.djangoproject.com/en/5.2/intro/overview/).
- **State:** PostgreSQL for development, CI integration tests, and deployment. One schema stores source/version relationships, decisions, jobs, publications, sessions, revisions, evaluation records, and usage. JSON/JSONL is import/export, not a second authoritative store.
- **Worker:** One separately running Python worker using durable database jobs, leases, heartbeat/recovery, idempotency keys, and a transactional outbox. Start with concurrency one; test competing claims anyway. Do not add Redis or a workflow service without a demonstrated need.
- **Storage and retrieval:** Local filesystem and deterministic retrieval adapters for development; private S3 snapshots/curated artifacts and Bedrock Managed Knowledge Base for live use. Fetch normalized evidence through the application, then call the drafting model separately so eligibility and evidence packets remain inspectable.
- **Authentication:** A maintained Microsoft Entra OIDC integration, server sessions, and an application allowlist initially containing Nicholas only. Later users join the same collection-access group. User drafts default to their creator; equal corpus access does not implicitly share private writing sessions.
- **Hosting candidate:** One small AWS EC2 host running the web app, worker, PostgreSQL, and TLS proxy in containers; encrypted persistent storage and off-host backups. Use an instance role, not copied developer credentials. CloudFormation is the initial infrastructure-as-code choice. This accepts single-host downtime for alpha and needs a measured resource/cost check before deployment. Managed database or alternate hosting is a documented substitution if the candidate cannot meet the acceptance or cost envelope.
- **Frontend dependencies:** Prefer assets requiring no Node build. If Node modules are needed, install/use them under the user's `.codex` root, including browser tooling; never in OneDrive. Track dependency declarations/locks and make the bootstrap reproduce the external dependency location.

AWS currently documents a distinct Managed KB retrieval configuration and filter limitations; do not copy a customer-managed vector configuration into this adapter. The intended account still needs a live capability test. [AWS retrieval guidance](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-test-retrieve.html).

## Nonnegotiable boundaries

Originals stay read-only. Private sources, excerpts, screenshots, evaluations, prompts containing private text, credentials, and raw responses stay out of Git and public PR comments. The application database owns corrections. Every item has a disposition. Excluded passages physically stay out of publication and model context. Voice approval is independent of technical eligibility. Historical proposals do not become current scientific truth. User edits and source-version citations survive regeneration and sync. Source instructions are data and cannot direct tools or override application policy.

The supplied specification's budget becomes the deployment planning envelope: $300–$500 setup/testing, never above $500 without an owner decision; target total recurring operations at $50/month, ceiling $100/month. Measure gross costs separately from credits. Developer subscriptions and review-tool charges are shown separately and are not assumed covered by AWS credits. See the setup checklist for allocations and stopping rules.

## Agent workload and owner rhythm

Use GPT-5.6 Sol for bounded implementation and routine fixes; use GPT-6 Astra for architecture, lifecycle/concurrency work, difficult integration failures, and independent review. This routing is a planning judgment, not a benchmark promise. Record the actual coding model at handoff; availability can vary. OpenAI's current catalog identifies both models, but no OpenAI runtime API dependency is required by this product. [Official model catalog](https://developers.openai.com/api/docs/models).

Each PR receives a focused handoff, a small internal implementation plan, tests tied to acceptance IDs, and an owner demo. Nicholas's usual task is to inspect the demo and merge after review. Batch genuine owner decisions at these boundaries: tooling access in 00, interaction feedback in 02, voice/task calibration in 05/07, connection session in 08, usefulness sign-off in 09, expansion approval in 10. Do not repeatedly ask for credentials while independent implementation remains.

## Current status

Planning is complete. MVP-00 and MVP-01 are merged; their implementation evidence is maintained in
`docs/mvp/implementation/`. MVP-02's local product-slice implementation and demo are recorded there
for its review boundary. No cloud resource, private-data connection, or paid provider call is
created by MVP-02.
