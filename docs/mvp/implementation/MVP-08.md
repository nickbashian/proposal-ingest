# MVP-08 implementation and connection evidence

Base: merged `main` at `2a6d6d3` (MVP-07, PR #23). MVP-08 offline work is on
`codex/mvp-08-operations-connections`. The [PR card](../PR_PLAYBOOK.md) and
[acceptance matrix](../ACCEPTANCE.md) are the gates; synthetic results do not
substitute for live service or private-corpus evidence.

| ID | Current status | Evidence required to close |
|---|---|---|
| 08-A | Offline implementation verified; live restore pending under 08-E | Deployment definition, production image build, Compose/config checks, held reindex tests, and a disposable PostgreSQL/object backup-and-restore drill passed. See [deployment notes](MVP-08-DEPLOYMENT.md) and [reindex procedure](MVP-08-REINDEX.md). |
| 08-B | Offline implementation verified; live usage comparison pending | Authenticated jobs/usage view, durable restart/budget/outage tests, redacted output and bounded logging. See [operations notes](MVP-08-OPERATIONS.md). |
| 08-C | **Pending live connection** | Account, region, quota/model/KB APIs, cost and credits, OIDC/SharePoint grants, bucket/privacy and denial checks. See [connection preflight](MVP-08-CONNECTIONS.md) and [cost preparation](MVP-08-COST.md). |
| 08-D | **Pending live connection** | One approved family through repeat sync, supervised classification/review, curated S3/KB, exact citations, writing, update/retirement and stale-result rejection. |
| 08-E | **Pending live connection** | Isolated restore/reindex, historical citations, cancellation/quota handling, measured recovery and actual gross costs. |

The connected acceptance sequence and the batched owner actions are in
[FINISH_LINE_SESSION.md](FINISH_LINE_SESSION.md). No private source, credential,
account identifier, prompt, model response, or private evaluation appears in this
report. The final offline canonical check passed 662 tests with static,
configuration, and secret/private-artifact gates. The final production image
built successfully, passed `python -m django check` in synthetic production
mode and nonroot `collectstatic` in isolated local mode, and Compose rendered
against the redacted template. The image smoke test exposed a missing installed-resource
root; the image now carries configuration and prompt templates under an explicit
`PROPOSAL_PROJECT_ROOT`. A disposable PostgreSQL 18 drill backed up one synthetic row and one
SHA-256-addressed object in 1.06 seconds; restore into an empty database under
publication hold completed in 0.93 seconds, with row and object hash verified.
The drill exposed a missing `pg_restore --dbname` argument, which was fixed and
covered by a regression assertion. These tiny local timings do not establish
the proposed 24-hour production RPO or four-hour RTO. The disposable database,
network, and client image were removed after verification.

CodeRabbit CLI 0.8.0 completed an initial local full-diff review after Nicholas
signed in. Its seven comments were checked against the code:

| Finding | Disposition |
|---|---|
| Backup stage hidden by systemd `PrivateTmp` and unreadable by the app-user packaging container (two comments) | Fixed with a root-only stage under `/var/lib/proposal-ingest`, `ReadWritePaths` for that host path, and root-user packaging. Kept `PrivateTmp` because it isolates only `/tmp` and `/var/tmp`, not the new stage. The production image packaged a synthetic bundle with that user override. |
| `pg_restore` target and missing `psql` error handling | The actual restore drill found and fixed the explicit `--dbname` requirement; the review's `psql` error mapping was then fixed and covered. |
| Bundle-integrity test's database-check guard installed too late | Fixed the test ordering. |
| Compose environment secret quoting (two inconsistent comments) | Reject backslashes; retain Docker Compose's documented escaped-apostrophe syntax. Added focused tests. |
| Amazon Linux Compose plugin installation | Replaced the unavailable assumed package with a pinned, checksum-verified official plugin binary and a version check in UserData. |

The corrected scripts and extracted UserData passed Linux `bash -n`; CloudFormation
YAML parsed, and the focused recovery/connection suite passed. The final-head
CodeRabbit follow-up reviewed all 51 changed files and produced two additional
valid deployment findings. UserData now starts the IMDS firewall service on first
boot, and the backup timer installer rejects a checkout outside its fixed
`/opt/proposal-ingest` service path. Linux syntax and the explicit custom-path
rejection were verified in the image. Required CI must pass on the follow-up
commit; the offline evidence does not close 08-C/D/E. A later offline preflight
against `.env.production.example` exposed placeholder Entra/SharePoint settings
incorrectly reported as configured. The preflight now marks template values
unresolved without printing them, and the production-template regression passed.
