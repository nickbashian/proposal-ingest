# MVP-01 operator guide

This foundation runs on PostgreSQL and the application services. It does not connect a live
corpus or implement the MVP-02 writing workflow. All demo data is synthetic.

## Start the application

From the repository root, bootstrap the locked Python environment, then:

```powershell
make db-up
make app-migrate
make fixture-job
$env:PROPOSAL_LOCAL_AUTH_ENABLED = 'true'
make app-run
```

Open `http://127.0.0.1:8000/login/`, select local sign-in with `fixture-owner`, and create a
synthetic fixture job. In another terminal run `make worker`. The job page shows durable status,
attempts, reservations, and accounted cost; refresh to see completion. The handler reads only
the repository's synthetic source fixture through the existing package's hashing utility.
`python scripts/manage.py worker --once` processes a bounded iteration. Ctrl+C stops polling;
after an abrupt termination, a new worker reclaims the job after its lease expires.

Windows uses `.venv/Scripts/python.exe`; Linux uses `.venv/bin/python`. The Make targets select
the correct interpreter. Application settings use process environment, **not automatic `.env`
loading**. Export needed values from a private environment/service configuration. Local sign-in
is off by default even though the example file describes enabling it. The development server
refuses non-loopback binds. Production WSGI settings reject local sign-in and require explicit
database, secret key, allowed hosts, and complete HTTPS OIDC configuration.

## Reproduce acceptance and the restart demo

```powershell
make check
.venv/Scripts/python.exe -m pytest tests/test_application.py tests/test_application_process.py -v
```

These tests create a disposable PostgreSQL **test database**, apply all migrations, exercise
constraints, signed synthetic OIDC tokens, ownership, concurrent workers/reservations, and open
Chromium against the actual application. The process test injects latency only into the local
adapter, kills the real management worker after its reservation commits, waits for expiry, then
starts a fresh worker process. Expected result: one JobResult, two attempts, the first reservation
unknown and retained, the second reconciled to zero. The browser test denies anonymous access,
logs in locally, creates a job, runs a separate worker, inspects completion/usage, and signs out.
No fixture accuracy or live-service claim follows from these tests.

## Authentication and collection access

The OIDC boundary uses Authlib's authorization-code flow with PKCE, session state, nonce,
signature, expiration, exact issuer, and audience validation. Configure `OIDC_ISSUER` to the
tenant-specific Entra v2 issuer and set `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET`, and
`ENTRA_REDIRECT_URI`. Production additionally needs a strong `PROPOSAL_SECRET_KEY`, explicit
`DATABASE_URL`, and `PROPOSAL_ALLOWED_HOSTS`. TLS terminates at a correctly configured deployment
boundary; forwarded headers are not trusted by this foundation. Production database URLs must
include `sslmode=verify-full` (or `verify-ca`); libpq's `PGSSLROOTCERT` can supply the private CA
file. Unsupported/repeated URL query options are rejected instead of silently discarded.

Provision an exact subject through a trusted operator terminal (identifiers stay private):

```text
python scripts/manage.py allow_identity USERNAME --issuer ISSUER --subject SUBJECT --collection COLLECTION
```

Repeat with `--revoke` to revoke identity access immediately, including existing sessions, and
remove the named collection grant. Revoking an unknown identity is an error and creates no records.
Issuer + subject
is the identity; email/display name is never an enrollment credential. Successful login never
creates an allowlist entry. Logout is POST with CSRF and destroys the application session; it does
not terminate other Microsoft applications' sessions. OIDC start requests account selection again.
No public admin, database, object-storage directory, or media route is exposed.

Every route defaults to authenticated access. Every corpus/job/artifact service checks collection
membership. Private draft sessions, revisions, packets, and exports also resolve creator ownership
from their stored parent chain; client-supplied IDs never transfer ownership. Updates create
revisions; deletion tombstones the session and preserves historical records. Generation is
explicitly unavailable until its later adapter/workflow exists. Unsupported draft actions still
perform authorization before reporting the unsupported operation.

## Job and cost semantics

- States: queued, running, delivering, succeeded, paused, canceled, failed, budget_stopped,
  quota_stopped, disabled. The job page supports pause/resume/cancel; terminal jobs cannot resume.
- Attempt UUIDs fence leases. Workers claim with PostgreSQL row locks and skip locked jobs.
  Heartbeats extend only a currently valid lease. Provider implementations must use bounded
  timeouts and call the heartbeat service during longer operations.
- Reserve before dispatch. Each retry gets a separate reservation. Global setup and calendar-month
  accounts plus the job cap are locked transactionally. Defaults: $500 setup, $50 monthly, $5/job.
  Missing responses retain the full upper estimate across restarts. Known actual usage reconciles
  the original accounts even when cancellation/expiry prevents accepting the result.
- A reservation commit is the dispatch boundary. Cancellation prevents subsequent attempts;
  already authorized in-flight work may finish and is accounted for, but cannot commit results.
  Cancellation before outbox delivery prevents that delivery too.
- Unknown outcomes remain charged conservatively until evidence resolves them. Operator changes
  must not erase reservations to force a retry. A new job/collection cannot reset global limits.
  Lower environment caps take effect on subsequent reservations; higher configuration does not
  automatically raise an existing database account cap. Infrastructure spend is outside this ledger.
- `JOB_MAX_ATTEMPTS` includes the first attempt (default 3); `JOB_LEASE_SECONDS` defaults to 120.
  Exponential retry delay starts at `JOB_BACKOFF_SECONDS` (default 5). The older `JOB_MAX_RETRIES`
  setting is retained for CLI/config compatibility and does not control the application worker.
- Result creation, audit entry, and outbox acknowledgment share a database transaction. MVP-01
  delivers a database effect only. Remote publication must later provide idempotent requests plus
  reconciliation; a database lease cannot guarantee exactly-once remote execution.

`SETUP_COST_LIMIT_USD`, `MONTHLY_VARIABLE_COST_LIMIT_USD`, and `SINGLE_JOB_COST_LIMIT_USD` override
the defaults. Startup refuses a configured setup allowance above $500 or monthly allowance above
$100. This is an application variable-cost boundary, not a claim that hosting fits the envelope.

## Data contracts and adapter boundary

SourceItem uses connector/tenant/site/drive/item identity. SourceVersion stores an observation key,
optional upstream version/ETag, content blob, and observed time. Unknown historical versions remain
null. Equal bytes share an immutable local object while retaining distinct items and proposal
memberships. The local storage adapter verifies hashes and installs completed files atomically
without overwriting existing bytes. Configure `PROPOSAL_LOCAL_STORAGE_ROOT` outside source roots;
the default is ignored `tmp/app_storage`. Back up this directory alongside the database. A database
rollback can leave an unreferenced immutable object; no automatic deletion is performed.
ExtractedUnit binds its locator to one source version and extractor revision. Database triggers
prevent parent/owner reassignment and history mutation, and validate cross-session packets,
membership collections, and publication provenance. Decision events are append-only with optimistic
revision checks; scoped conflict resolution remains MVP-05 work.

Protocols in `proposal_app/adapters.py` define enumeration/download, extraction, classification,
immutable object storage, publication/reconciliation, retrieval candidates, and drafting. All live
capabilities report disabled; missing credentials do not prevent startup. The local fixture handler
uses the same job and accounting services. Future retrieval candidates must pass
`services.eligible_artifacts`; a provider cannot grant eligibility. Full decision invalidation and
publication activation are later PR scope, not implemented through this helper alone.

`services.import_legacy` reads and deduplicates legacy JSONL into a database import envelope,
preserving human corrections verbatim. It does not guess connector identities or promote legacy
records into the corpus. MVP-03 maps this staging boundary. Application services never dual-write
the old MetadataStore. The historical CLI remains available for its independent prototype runs.

Provider error fixtures cover Graph `error.code`, Bedrock `Error.Code`, throttling, denial,
quota, and uncertain timeout outcomes. Raw provider messages are not persisted/displayed.
References checked during implementation:
[Graph errors](https://learn.microsoft.com/en-us/graph/errors),
[Bedrock Converse errors](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html),
[Authlib Django integration](https://github.com/authlib/authlib/blob/main/authlib/integrations/django_client/apps.py),
[Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).

## Migration, backup, and restore

Stop web writes and workers before a migration, create a logical backup, and verify it before
changing an existing database. Keep backups private. For the disposable Compose environment:

```text
docker compose -f compose.dev.yml exec -T postgres pg_dump -U proposal_ingest -Fc -f /tmp/pre-migration.dump proposal_ingest_dev
docker compose -f compose.dev.yml cp postgres:/tmp/pre-migration.dump db_dumps/pre-migration.dump
python scripts/manage.py migrate
```

Create the ignored `db_dumps` directory first. Copy the dump to protected backup storage for real
operations; a container-local dump alone is not a backup. Verify restoration to a **new** database,
using `createdb` and `pg_restore --exit-on-error --no-owner --dbname=RECOVERY_DATABASE` inside the
container, then point an isolated application at it and inspect records. Never use `db-reset` on
retained application data. Do not restore over an active database.

Migration `0002_provenance_guards` is intentionally irreversible. Rollback means stop writes,
restore the pre-migration database into a separate database, run the matching prior application
revision, verify records/access, and explicitly switch the connection. Do not assume a reverse
migration recovers state. Production backup/restore automation, off-host retention, publication
reconciliation after restore, and recovery timing targets belong to MVP-08.
