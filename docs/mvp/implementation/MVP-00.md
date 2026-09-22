# MVP-00 implementation report

- **Date:** 2026-09-22
- **Branch:** `codex/mvp-00-environment-guardrails`
- **Base:** `4143a328aef2ee773806b0f17d7f7da375adac9c`
- **Coding agent:** Codex
- **Migration/rollback:** No application migration. Revert repository tooling/configuration changes;
  `make db-reset` removes only the named disposable development database volume.

## Baseline reconciliation

Before changes, Python 3.13.13 passed Black, Ruff, codespell, mypy, and all 296 tests. The code and
root README showed that prototype phases 1–12 and 14–16 were implemented, while `AGENTS.md` and the
GitHub phase instruction incorrectly called Phase 12 a stub/next task. The current commit matched the
planning baseline. The supplied version 0.2 product specification itself was not present; its name
and SHA-256 remain recorded in `docs/mvp/README.md`. Existing user planning files and the unrelated
untracked `-A8.git` were preserved.

## Acceptance evidence

| ID | Status | Evidence |
|---|---|---|
| 00-A | Passed on Windows; Linux CI pending PR | GNU Make 4.4.1 ran literal `make check`: Black, Ruff, codespell, mypy, configuration/secret scans, 328 tests, and Chromium smoke all passed. Linux uses the same Make target in `.github/workflows/ci.yml`; final hosted evidence is recorded in the PR. Python is constrained to exactly 3.13 and the 3.12 fallback was removed. |
| 00-B | Passed | Locked bootstrap completed from `requirements-dev.lock`; Chromium installed beneath the nonsynced `.codex` root. `make mock-run` processed the synthetic fixture with no AWS call: 6 inventoried, 5/5 eligible analyzed, 5 copied, 1 excluded, 6 manifest rows. Output stayed under `tmp/mvp00-mock`. |
| 00-C | Passed | `scripts/dev.py diagnose` reports Git/Python/Make/Docker/Compose/AWS CLI/GitHub CLI/Node/Playwright/CodeRabbit separately and distinguishes absent executable, inactive service, and missing/unverified sign-in. The pinned PostgreSQL 18.6 service passed health, restart-persistence, and logical-backup checks; `db-reset` removed its disposable volume. |
| 00-D | Passed locally; hosted CI pending PR | Local/CI use `make check`, ordinary CI forces mock mode and disables AWS metadata access, and the repository scanner rejects common credentials and forbidden private-artifact paths without printing values. Synthetic provenance and private-data policy are documented. GitHub readback confirmed auto-merge disabled and `main` protected with current branch plus `check` required, admins included, conversation resolution, and force-push/deletion disabled. |
| 00-E | Passed | `AGENTS.md`, root README, GitHub instructions, and old roadmap/pilot headers now identify the MVP roadmap as active. Read-only sources, config-driven behavior, mock mode, checks, and historical pilot status are preserved. |
| 00-F | Passed locally; GitHub App optional | CodeRabbit CLI 0.8.0 was installed from an inspected official installer. `cr auth status` succeeded and `cr doctor` reported 9/9 checks passing. Final-diff review evidence and dispositions are added below. The GitHub App remains optional because a full local CLI review satisfies the playbook. |

## Environment and connection matrix

“Verified live” means an account/service interaction occurred; installed software alone is not a
live verification.

| Item | Implemented/configured locally | Verified in live account | Responsible / next action |
|---|---|---|---|
| Python/dependencies | Python 3.13.13; pinned lock; bootstrap passed | Not applicable | Agent; CI repeats on Linux |
| GNU Make/checks | Make 4.4.1; canonical target passed | GitHub-hosted run pending PR | Agent |
| Browser tooling | Playwright 1.63.0; local Chromium render passed | Not applicable | Agent |
| Docker/PostgreSQL | Engine 28.4.0; Compose 2.39.2; PostgreSQL smoke/cleanup passed | Not applicable | Agent; start Docker Desktop when developing |
| GitHub | CLI authenticated; public repository; protected `main`; auto-merge off | Repository settings read back 2026-09-22 | Nicholas retains final merge authority |
| CodeRabbit | CLI 0.8.0 authenticated; doctor passed | Local review service reachable | Agent records final review below; GitHub App optional |
| AWS | CLI and named profile detected | No identity, billing, model, quota, or region capability probe | Nicholas/agent in the MVP-08 connection session |
| Entra/SharePoint | Empty settings contract only | Not connected | Tenant administrator plus agent in MVP-08 |
| TypeSafe/Jev | Disabled empty settings contract only | Terms and account unverified | Nicholas/agent at MVP-05/08 decision gate |
| Production hosting/storage | Not provisioned by design | Not connected | MVP-08 after offline implementation and cost review |

## Design and data decisions

- `decisions/0001-product-foundation.md` records the proposed Django/PostgreSQL/database-worker,
  adapter, OIDC, deployment, and no-Node defaults. Merge is the owner confirmation gate.
- The source archive remains read-only. Repository fixtures are fictional and carry explicit
  provenance. Private excerpts, screenshots, evaluations, prompts/responses, dumps, and state files
  stay outside Git and CodeRabbit.
- PostgreSQL is setup-only in MVP-00. Application models, migrations, worker startup, and browser
  application flows remain MVP-01/02 scope.

## CodeRabbit review

- **First reviewed commit:** `7c0167d` (full committed diff against `main`).
- **First result:** Review completed across all 30 changed files with seven findings (six unique; the
  database-dump suffix finding appeared twice).
- **Finding dispositions:** All unique findings were substantiated and fixed. The shared browser
  installer now owns the `.codex` cache and Linux system dependencies; Python validation rejects
  3.14; Make/CI use the shared installer; `.dump`/`.sql.gz` are forbidden; and placeholder safety
  requires a full-value match. Four regression tests cover these corrections.
- **Second reviewed commit:** `de3c06c` (full committed diff against `main`).
- **Second result:** Three substantiated findings: CodeRabbit filters omitted some dump/state
  patterns, required settings accepted blank values, and files beyond the scanner size limit were
  skipped.
- **Second dispositions:** All were fixed. Review filters now match repository artifact policy;
  required settings and the storage-backend enum are validated; oversized UTF-8 files are streamed,
  unallowlisted oversized binary files fail closed, and explicit synthetic binary fixtures are the
  only exception. Three regression tests cover these corrections.
- **Third reviewed commit:** `ff48726` (full committed diff against `main`).
- **Third result:** Three substantiated edge cases: backend-specific storage settings were not
  required, non-finite cost limits passed validation, and small binary/Terraform state derivative
  artifacts were not fully fail-closed.
- **Third dispositions:** All were fixed with seven parametrized regression cases. Local storage and
  S3 now require their backend-specific settings, cost limits must be finite and positive, and all
  unallowlisted binary and Terraform state derivative files fail the repository guard.
- **Fourth reviewed commit:** `ce7bc55` (full committed diff against `main`).
- **Fourth result:** Two unique substantiated findings (one was duplicated): the direct Python check
  flow omitted configuration validation, and credentials embedded in remote URI user-info were not
  detected.
- **Fourth dispositions:** Both were fixed. The direct check and Make/CI paths now run the same
  configuration validation, and URI credentials fail the repository guard with one exact documented
  loopback development URI exception. Two regression tests cover these corrections.
- **Fifth reviewed commit:** `f82b737` (full committed diff against `main`).
- **Fifth result:** Three unique substantiated findings (one was duplicated): the local pre-commit
  scanner used the ambient interpreter, symbol-prefixed/lowercase secret assignments could evade the
  heuristic, and binary-fixture exceptions trusted paths without content verification.
- **Fifth dispositions:** All were fixed. Pre-commit creates a Python 3.13 hook environment, assignment
  detection supports lowercase keys and quoted symbol-prefixed values without treating Python
  expressions as credentials, and every binary exception requires its recorded SHA-256. Two
  regression tests cover the scanner changes; the managed pre-commit hook passed.
- **Sixth reviewed commit:** `a5510f6` (full committed diff against `main`).
- **Sixth result:** Two findings. The missing `AWS_SECRET_ACCESS_KEY` assignment family was
  substantiated. Scanning every ignored local file was rejected: acceptance 00-D protects the Git
  boundary, and `git ls-files --cached` already scans an ignored file if force-added; traversing
  ignored `.venv`, outputs, and deliberately private local data would violate the documented scope
  and expose private content to a routine check.
- **Sixth dispositions:** AWS secret-access-key assignment detection and a regression test were
  added. Candidate discovery remains limited to tracked plus nonignored untracked files by design.
- **Seventh reviewed commit:** `73f72bf` (full committed diff against `main`).
- **Seventh result:** Two unique substantiated findings (one was duplicated): environment-variable
  expansions with embedded defaults were treated as placeholders, and only the first credential
  assignment on a line was checked.
- **Seventh dispositions:** Both were fixed. Only plain environment-variable references are safe,
  and every assignment on a line is evaluated. Two regression tests cover the evasion cases.
- **Eighth reviewed commit:** `5abb017` (full committed diff against `main`).
- **Eighth result:** One substantiated finding required `--production` to agree with
  `PROPOSAL_APP_ENV`. The repeated ignored-file finding was rejected for the reason recorded above.
  A contradictory suggestion to mandate an Entra client secret was rejected: the future auth
  contract permits a secret, certificate, or managed credential source, and MVP-00 has not selected
  one. A later finding in the same review explicitly agreed not to add that requirement.
- **Eighth dispositions:** Explicit production validation now requires the production environment,
  with regression coverage. No future authentication mechanism was prematurely hardcoded.
- **Ninth reviewed commit:** `a1eb99a` (full committed diff against `main`).
- **Ninth result:** Three unique substantiated findings (the Python-constant finding was duplicated):
  malformed environment files could escape the concise CLI error path, an existing stale `.venv`
  was reused without checking its interpreter, and Python constant secret assignments were broadly
  exempted.
- **Ninth dispositions:** All were fixed. Configuration parse errors return a concise failure, an
  existing virtual environment must report Python 3.13, and AST-based scanning detects sensitive
  string, byte-string, numeric, and multiline constants while allowing nonconstant lookups/calls.
  Three regression tests cover these paths.
- **Final verification:** Pending review of the final fix commit; the result is also recorded in the
  PR before merge.

## Known limitations and next handoff

- Hosted Linux CI cannot be called passed until the branch is pushed and the PR check completes.
- No production/account capability was inferred from installed CLIs or templates.
- MVP-01 starts only after this PR merges. It owns the durable Django application, PostgreSQL
  migrations, authenticated shell, durable worker/jobs, and adapter contracts.
