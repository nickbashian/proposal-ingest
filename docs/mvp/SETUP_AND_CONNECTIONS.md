# Setup, connections, and operating envelope

This checklist is owned by MVP-00 and updated in every PR. MVP-00 added repository diagnostics,
locked setup, browser/database smoke paths, and review guardrails. Authentication, cloud
capabilities, billing, and production connections remain **unverified**;
see `implementation/MVP-00.md` for dated evidence and exact pending owner actions.

MVP-01 adds the Django/PostgreSQL application, OIDC boundary, durable worker, reservations,
and local acceptance workflow. See `implementation/MVP-01.md` and `MVP-01-OPERATIONS.md` in
the implementation directory. Live connections remain unverified; no deployment was provisioned.

MVP-02 adds the worker-loaded synthetic family and complete local review-to-export product slice.
See `implementation/MVP-02.md` and `MVP-02-OPERATIONS.md`. It needs no live credential and makes no
provider call; all connection statuses below remain unchanged.

Use two status columns in the implementation report: **implemented/configured locally** and **verified in the live account**. Record date, evidence location, responsible person, and next action for anything pending. Keep credentials and sensitive account identifiers in private configuration, not this checklist or PR comments.

## Phase 0 installation and environment checklist

| Item | Current evidence | Phase 0 action and completion proof |
|---|---|---|
| Working copy | Existing clone at `C:\dev\Proposal RAG Assistant`; baseline commit in overview | Preserve unrelated edits/untracked files; branch from verified merged main. Keep code/dependencies outside OneDrive. |
| Python | Existing `.venv` runs Python 3.13.13 and tests | Lock compatible runtime/development dependencies; test fresh environment setup. Document interpreter selection and portable Windows/Linux commands. |
| Make | GNU Make 4.4.1 ran the canonical Windows gate | Keep literal `make check` working on documented Windows and Linux paths; fail immediately on each failing component. |
| PostgreSQL | PostgreSQL 18.6 service health, restart persistence, logical backup, and disposable cleanup passed | Keep MVP-00 validation limited to the disposable service. MVP-01 owns application migrations and database integration tests. |
| Docker | Engine 28.4.0 and Compose 2.39.2 ran the PostgreSQL smoke path | Document native-Windows/WSL prerequisites and how to start/stop the development stack. |
| Git/GitHub CLI | Executables present | Verify repository remote and `gh auth status`; inspect visibility and required-check capabilities. Configure PR template, checks, and Nicholas-only merge workflow within available account features. |
| Formatting/tests | Black/Ruff/codespell/mypy and 342 pytest cases passed | Keep locked versions aligned with hooks/CI and preserve one canonical check path. Add migration drift and application checks in their owning MVPs. |
| Browser tests | Python Playwright 1.63.0 Chromium smoke passed locally and in CI | Keep browser binaries in the nonsynced `.codex` cache and preserve the Linux dependency installation path. |
| Node/assets | Node executable present | No Node installation is needed merely because this is a web app. If selected, declare/lock modules in repo but install/use at the owner's `.codex` root; support isolated per-project dependencies beneath that root. No dependencies in synced directories. |
| AWS CLI | Executable present | Verify version and named-profile/SSO setup when connecting; do not run a model smoke test as a default setup step. |
| CodeRabbit | CLI 0.8.0 authenticated; doctor passed 9/9; PR review path active | Prefer GitHub app review for durable findings and keep any remaining interactive sign-in in the shared owner list. |
| Configuration | Prototype `.env.example` exists | Extend with local/production mode, DB, storage, auth, connector IDs, per-task models, provider enable flags, job/budget limits, retention. Validate missing/invalid settings with actionable diagnostics; no secrets in defaults. |
| Data separation | Existing ignore rules cover common output folders | Add explicit private-data/evaluation/screenshot locations, secret scanning, synthetic fixture provenance, and safe logging. `.gitignore` alone is not a confidentiality check. Keep containers/DB dumps and infra state out of commits. |
| Agent instructions | Historical status conflicts with actual code | Reconcile AGENTS, README, GitHub instructions, and old roadmap pointers. Preserve American English, source immutability, config-driven behavior, mock mode, and mandatory checks. |

Phase 0 should add and smoke-test documented commands for environment diagnosis, dependency/database setup, the existing mock pipeline, checks, and teardown of its development services. MVP-01 adds migration and app/worker startup commands; MVP-02 adds end-to-end application fixture loading. Do not create placeholder commands or build later application components merely to satisfy Phase 0. Choose actual names when the corresponding components exist and smoke-test them. The root README should make the shortest currently working setup path obvious.

CodeRabbit's CLI documentation was rechecked on September 22, 2026. The supported commands are
`cr auth login`, `cr auth status`, `cr doctor`, and `cr review`; the current Windows path is a
PowerShell installer. Download the installer to a temporary file, inspect it, then execute it—do
not pipe network content directly into PowerShell. A normal review does not consent to paid
over-limit usage; never pass `--use-credits` without explicit owner approval. [CodeRabbit
CLI](https://docs.coderabbit.ai/cli), [VS Code
extension](https://marketplace.visualstudio.com/items?itemName=CodeRabbit.coderabbit-vscode).

## Build-first connection sequence

Prepare production adapters, settings templates, diagnostics, infrastructure definitions, and synthetic contract tests before asking Nicholas to connect services. Review current provider documentation while writing each adapter. Credential availability is not evidence of a correct request schema; documentation is not evidence that the account supports it.

At MVP-00, collect setup prerequisites in one place. At MVP-08, arrange the focused session below when all feasible offline work is ready. If Nicholas makes access available sooner, bounded read-only diagnostics and synthetic service probes can reduce risk early; avoid deploying an idle paid stack months before it is needed.

### 1. GitHub and review tooling — owner plus implementing agent

- Verify repository visibility and where sanitized versus private evidence belongs. Changing visibility is an owner choice, not a prerequisite for protecting data.
- Enable CodeRabbit for this repository, verify a real review result, and document local-review fallback. Do not purchase a plan or enable paid over-limit review silently.
- Set CI as a required merge check where supported; keep automated merge disabled. Document review behavior for draft PRs/bot-created PRs so skipped reviews are visible.

### 2. AWS identity, region, capabilities, and costs — owner plus implementing agent

- Use the intended account and an SSO/named profile for development. Verify identity with `aws sts get-caller-identity --profile <configured-profile>` in a private session. Never assume the historical pilot's account/profile is still correct.
- Verify selected region and the current SDK's Managed KB API support, create/ingest/query/delete lifecycle, metadata representation/limits, S3 datasource behavior, quotas, model access, and required inference-profile IDs. The prior Opus profile is a baseline candidate, not proof of current access or an economical default.
- Prefer a supported US region consistent with existing data policy. AWS's published Managed KB region list includes US East and US West options; verify the chosen account/service endpoint rather than assuming regional documentation establishes entitlement. [Supported regions](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-regions.html).
- Implement the Managed KB request shape using `managedSearchConfiguration` where configured, not `vectorSearchConfiguration`. AWS documents managed hybrid search and differences in supported metadata operators; test exact filters and artifact identity round-trips. [Retrieve guidance](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-test-retrieve.html).
- Keep the source connector under application control: publish curated S3 artifacts to the KB. Do not bypass curation with the service's direct SharePoint connector. Verify parser/chunking settings preserve mapping back to curated artifact/source units. [Managed KB creation](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-create.html).
- Separate provisioning permission from runtime roles. Scope application/worker/KB service roles to required buckets/prefixes, model profiles, KB, and secret access. Confirm private buckets, encryption, TLS, metadata-service protection, and no public database port. Restrict infrastructure deletion to resources created for this application.
- Build a cost sheet from current pricing and measured representative usage. Record credits' eligible services, expiration, and actual account applicability privately. Create billing alerts and application limits before paid tests. Set model max-token/timeout/retry budgets and job scope limits.
- Run a synthetic minimal live lifecycle first, then one approved family. Capture sanitized API capability evidence and service failures. If the account cannot support Managed KB, keep local development working and present a costed alternative; do not silently select a different retrieval backend.

### 3. Microsoft Entra and SharePoint — Nicholas/tenant administrator plus agent

- Register/configure web-app OIDC login with exact redirect/logout URLs, intended tenant, secure credential/certificate storage, and app access limited to Nicholas initially. Validate issuer/audience/session expiration and failed/unauthorized sign-in.
- Separately configure the background source connector's identity. Prefer selected-site application access with an explicit read grant to the grant site; validate that it supports the operations used. Do not request broad tenant write permissions. Tenant consent and the resource-specific grant are distinct steps. [Microsoft Selected permissions](https://learn.microsoft.com/en-us/graph/permissions-selected-overview).
- The MVP-03 connector reads `ENTRA_TENANT_ID`, `SHAREPOINT_SITE_ID`, `SHAREPOINT_DRIVE_ID`, `SHAREPOINT_CLIENT_ID`, and `SHAREPOINT_CLIENT_SECRET` at runtime. The SharePoint client ID and secret belong to the background read-only app and are separate from the web login's `ENTRA_CLIENT_ID` and `ENTRA_CLIENT_SECRET`. Keep both secrets outside source control. The operator supplies one proposal folder's drive item ID per sync command; the connector verifies its parent is the requested year folder.
- Resolve site, library/drive, and three seed-family folder identifiers in private settings; test recursive enumeration, paging, download/version metadata, and read-only access. Do not use a Codex connector's interactive session as the application's production credential.
- Test supported delta/checkpoint behavior. Where delta is not usable at the desired scope/permission level, perform scoped full reconciliation and declare completion only after all pages succeed. Resume/rescan expired checkpoints safely; absence during an incomplete crawl cannot retire content. [Graph driveItem delta](https://learn.microsoft.com/en-us/graph/api/driveitem-delta?view=graph-rest-1.0).
- Verify that curated S3 copies use the application's shared access policy; they do not inherit source document permissions. If unequal-access content is identified, stop that content's publication and resolve scope before onboarding users.

### 4. TypeSafe/Jev experiment — agent prepares; Nicholas resolves material ambiguity

- Implement the bounded typed-decision adapter with synthetic/public examples and task-specific abstention. Record actual model/API version and usage; do not assume AWS credits cover TypeSafe. [TypeSafe introduction](https://docs.typesafe.ai/introduction).
- Review the effective service terms, confidentiality, retention/deletion, training use, subprocessors, and applicability to proprietary nonpersonal proposal content before transferring selected private excerpts. Store URLs, dates, findings, account-tier terms, and decision privately where appropriate.
- Initial planning finding: the public privacy policy states that Input is not used for model training, but its retention language is broad and oriented toward personal data. That alone does not establish a bounded retention period for confidential proposal content. Treat the private-excerpt condition as **pending**, not satisfied; seek clarifying terms or Nicholas's decision on material ambiguity. [TypeSafe privacy policy](https://typesafe.ai/legal/privacy-policy), [data-processing addendum](https://typesafe.ai/legal/data-processing).
- MVP-05 review on September 24, 2026: the [Site Terms of Use](https://typesafe.ai/legal/terms) were updated September 19, 2026 and say not to submit confidential/proprietary information through the Site; they also say a separate product agreement governs product/service use when one exists. The [privacy policy](https://typesafe.ai/legal/privacy-policy) says Input is not used for model training and is not disclosed outside service providers, but does not establish a fixed confidential-input retention period. The [DPA](https://typesafe.ai/legal/data-processing) addresses customer personal data and points to a [subprocessor list](https://trust.typesafe.ai/subprocessors); it does not by itself settle terms for proprietary nonpersonal excerpts. Nicholas must review the actual account-tier product agreement, retention/deletion and subprocessor terms, and document the transfer decision privately before setting `PROPOSAL_JEV_PRIVATE_TRANSFER_APPROVED=true`. The Jev route remains disabled in application configuration until then. This is a material terms ambiguity, not a technical failure to be bypassed with a key.
- Once the documented condition is satisfied, the specification contemplates selected excerpts without repeatedly asking permission for each one. Whole-corpus transfer remains outside that scope. If terms/keys remain unavailable, continue Bedrock operation and report the experiment incomplete.

### 5. Deployment and real acceptance — agent plus Nicholas

- Verify host sizing/region/cost and DNS/TLS access before apply. Default candidate is a single EC2 host with containers and instance role; an authenticated HTTPS endpoint protects all application data. It is not a claim of VPN/network-only access. If network isolation is required, record that deployment decision and cost before proceeding.
- Apply reviewed infrastructure, load managed secrets, migrate, enable auth, and run the production security/health checks. No fixtures masquerade as real data; the local-auth switch is forbidden in deployed settings.
- Set separate retention rules for transient responses, failed-job artifacts, source snapshots, published excerpts, saved draft evidence, and backups. Cited excerpts/version context must remain available for retained drafts; retiring content from new retrieval is distinct from deleting its historical evidence. A deletion requirement that conflicts with this history needs an explicit recorded policy decision and a visible citation tombstone, not a silently broken link.
- Run one real family end to end, including a repeat sync, real draft, and precise citation opening. Then exercise isolated restore/reindex, quotas, cancellation, and artifact retirement. Save evidence privately and summaries in the PR.
- Continue to the three-family acceptance session only after this path works. Reserve a fourth family before tuning for the expansion gate.

## Budget and stopping policy

These are **planning allocations**, not quotes or commitments. Setup/testing includes cloud/service use through the initial build and testing period; reserve funds for full-year validation. If the allowance is nearly consumed, reduce scope or obtain an owner decision before further paid work. Do not hide overages behind credits.

| Setup/testing allocation | Target maximum |
|---|---:|
| Account probes, staging, deployment, and recovery drills | $75 |
| Three-family extraction, classification, reconciliation, and drafting evaluations | $175 |
| Held-out evaluation and initial full-year expansion | $100 |
| Unallocated contingency/repeated tests | $150 |
| **Total upper allowance** | **$500** |

The preferred execution target is about $300–$350, leaving contingency. Derive per-job caps from remaining allocations and corpus inventory, then reserve estimated worst-case spend before each call. Persist run and cumulative/monthly ledgers so restarts cannot reset allowances. A stopped job cannot be restarted to bypass an account/project cap. Restrict concurrent in-flight cost with worker concurrency and per-call upper bounds; count uncertain timed-out requests conservatively.

| Recurring category | Working allocation toward $50/month |
|---|---:|
| Compute, persistent disk, network/address charges | $22 |
| Object storage, backups, secrets, logging, DNS | $8 |
| Managed KB indexed storage and standard retrieval | $5 |
| Model use and any TypeSafe evaluation/operation | $15 |
| **Target total** | **$50** |

These allocations may fail at actual scale. Before deployment, replace every allocation with a region/service/usage-based estimate including minimums, request charges, network, backups, and taxes where applicable. Avoid adding an always-on load balancer, NAT gateway, managed vector cluster, or database tier without showing its total cost. At $50 forecast, surface the variance and optimization options; $100/month is the hard owner-decision boundary, not a spend target. Include idle cost, typical use, and a busy-month scenario.

For a starting cost model, AWS currently lists Managed KB raw indexed storage at $5/GB/month and standard retrieval at $1/1,000 calls, with managed parsing/embedding/reranking included. Thus 0.5 GB plus 1,000 standard retrievals is about $3.50/month **for those two components only**, before drafting, hosting, S3, logs, taxes, or alternate models. Confirm the account/region quote at deployment and measure indexed curated size; do not substitute total source archive size without checking billing semantics. [AWS Bedrock pricing](https://aws.amazon.com/bedrock/pricing/).

Track actual token/request counts and provider-reported charges where available; label calculated estimates separately. Billing alerts are delayed signals, not hard caps. App limits bound dispatched variable-cost work, while standing infrastructure continues billing until changed. Document how to pause workers, stop new model/retrieval calls, reduce or stop hosting, and retain required backups safely. Add retention and resource-expiration checks so forgotten staging resources cannot grow unnoticed.

Coding-agent subscriptions, CodeRabbit fees, domain purchases, and other development expenses belong in a separate transparent tooling line. Do not assume these are already paid, consume AWS credits, or are automatically authorized outside the agreed envelope.

## Ready-to-connect handoff

The agent presents one concise list: pending connection, precise owner/admin action, why required, the diagnostic to run afterward, expected maximum cost, and what can continue independently. Secrets are entered through the intended sign-in or secret store, never pasted into public comments. The deployment code, local demo, tests, and costed plan must already be reviewable before this session.
