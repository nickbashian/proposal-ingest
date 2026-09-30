# MVP-08 offline deployment and recovery implementation

Status: **implementation artifacts prepared; deployment and live checks not performed**.
No AWS resources, SSM parameters, public DNS, Entra application, SharePoint site, or Managed
Knowledge Base were created or contacted for this work. The infrastructure template is a
reviewable starting point and must be costed and parameterized before an owner-approved apply.

## Deployment shape

`infra/cloudformation/mvp08-single-host.yml` describes one encrypted-EBS Amazon Linux host,
a private-only database/container network, an Elastic IP, a TLS proxy, a private versioned S3
bucket, SSM access, and a scoped instance role. The runtime role is limited to the selected
Knowledge Base ARN, the supplied inference-profile/model ARNs, the one bucket, and four named
SSM parameters. The template does not create the Entra application, Managed Knowledge Base,
data source, DNS record, or model access grants. HTTPS ingress is restricted to an owner-provided
IPv4 CIDR; port 80 is public for Caddy's HTTP-01 certificate flow and redirects to HTTPS. Confirm
this exposure, host size, EIP, data region, and current service prices before deployment.
The role can delete only `curated/` objects; backup deletion is delegated to the bucket lifecycle.
Keep this IAM prefix aligned with `publication_s3_prefix` when deploying.
Host initialization installs Docker from Amazon Linux and the x86-64 Compose CLI plugin from a
pinned official release with a SHA-256 check, then verifies `docker compose version`. The Compose
plugin is a manual installation and needs an explicit maintenance update; verify its download
and Docker compatibility on the selected AMI during the live host setup.

Compose runs the pinned Python 3.13 application image, Gunicorn, one worker, PostgreSQL 18,
and Caddy. The host security group exposes only ports 80/443. PostgreSQL has no host-published
port and rejects clear-text TCP. The database server certificate must have `DNS:database` in its
SAN, and app/worker connections use `sslmode=verify-full` with the mounted private CA. The
application only trusts `X-Forwarded-Proto` when `PROPOSAL_TRUST_PROXY_SSL_HEADER=true`; in this
deployment only Caddy can reach Gunicorn. Compose collects static files into a shared volume,
which Caddy serves directly. A request to `/login/` with the production host and forwarded HTTPS
header is the container health check. Gunicorn access logs are disabled to avoid recording private
query strings and identifiers; application and proxy error logs still require restricted access
and retention controls.

The image sets `PROPOSAL_PROJECT_ROOT=/app` and includes only the required version-controlled
configuration, prompt templates, application source, and recovery script. The build context
excludes local environments, private data, and Git state. Run `python -m django check` inside
the image with complete offline placeholder configuration before deployment.

App source snapshots and curated bytes currently use `LocalObjectStorage`; the app has no S3
object-storage adapter. Production therefore stores this immutable object volume on the host's
encrypted EBS root volume. The private S3 bucket is used for curated Managed KB publication and
encrypted off-host backup bundles. Its Managed KB data source must include only the configured
curated prefix, never `backups/`. This does not claim that source snapshots are directly stored in
S3.

Docker bridge addresses `172.30.0.3` and `.4` are reserved for web and worker so the host's
`DOCKER-USER` rule can allow IMDSv2 credentials to those two containers and block other
containers. The CloudFormation metadata hop limit is 2 for that path. Check for a host Docker
network using `172.30.0.0/24` before bringing up Compose; change both the network/IP reservations
and the host firewall together if it overlaps. Live verification of the credential path is still
required.

## Private configuration and first start

Keep `.env.production` root-owned with mode `0600`; it is generated from SSM SecureString values
by `deploy/render_env_from_ssm.py`. The four parameter names are
`/proposal-ingest/prod/PROPOSAL_SECRET_KEY`, `/proposal-ingest/prod/ENTRA_CLIENT_SECRET`,
`/proposal-ingest/prod/SHAREPOINT_CLIENT_SECRET`, and `/proposal-ingest/prod/POSTGRES_PASSWORD`.
Set the nonsecret `SHAREPOINT_CLIENT_ID`, `SHAREPOINT_SITE_ID`, and `SHAREPOINT_DRIVE_ID` entries
to the approved read-only Graph app, site, and document library values. Create/update the
SecureString parameters privately with the AWS console or
AWS CLI; never put their values in command arguments, shell history, task output, or logs. The
PostgreSQL password must be exactly 64 hex characters because Compose places it in a URL. Generate
it with a private command such as `openssl rand -hex 32`. The Django secret must be at least 50
characters. The renderer captures secret output without printing it, single-quotes values for
Compose, writes atomically, and sets mode `0600`. Use `--replace` only as part of a planned secret
rotation; rotate the PostgreSQL role password in PostgreSQL and SSM together before recreating
the services. Entra and SharePoint client-secret rotation likewise require updating their distinct
SSM values and recreating app services. Grant the Graph app only the approved read-only site
permissions; the instance role retrieves the named secret but does not grant Graph access itself.

The same-host PostgreSQL CA private key stays under the root-only `private-ca/` directory and is
not mounted into containers. The leaf certificate and key are mounted read-only into PostgreSQL;
the CA certificate alone is mounted into app/worker. The script gives the server key to the
PostgreSQL container UID 70. Store an offline protected copy of the CA key and record a certificate
renewal date; the leaf certificate expires after 397 days.

After an owner-approved CloudFormation deployment, install the checkout at `/opt/proposal-ingest`,
point DNS at the stack's Elastic IP, provision the named SSM values, and run these host commands.
They are documented only; they were not run against AWS:

```bash
sudo bash deploy/create_postgres_tls.sh /etc/proposal-ingest/tls
sudo python3 deploy/render_env_from_ssm.py \
  --template .env.production.example \
  --destination /etc/proposal-ingest/.env.production
sudo docker compose --env-file /etc/proposal-ingest/.env.production \
  -f deploy/compose.production.yml build
sudo docker compose --env-file /etc/proposal-ingest/.env.production \
  -f deploy/compose.production.yml run --rm --no-deps web \
  python -m django migrate --noinput
sudo docker compose --env-file /etc/proposal-ingest/.env.production \
  -f deploy/compose.production.yml up -d
sudo docker compose --env-file /etc/proposal-ingest/.env.production \
  -f deploy/compose.production.yml ps
```

The production template starts with `PROPOSAL_PUBLICATION_HOLD=true` and live classification and
drafting disabled. Keep the hold in place while validating the restored state and source/decision
audit. No local-auth route is available in production. Do not clear the hold or enable paid model
calls based on Compose health alone.

## Backup and restore

`deploy/backup_to_s3.sh` takes a PostgreSQL custom-format dump from the pinned PostgreSQL 18
container over its local socket, packages the dump with every SHA-256-addressed immutable object,
verifies each object's content hash, and uploads the bundle with SSE-S3 to the versioned private
bucket. The database dump is taken before enumerating immutable objects, so new concurrent object
writes can only add a harmless superset; objects are never overwritten. The manifest records file
sizes and SHA-256 hashes. The systemd unit runs as root, writes only into a private temporary
directory under `/var/lib/proposal-ingest/backup-staging` that is visible to the Docker daemon.
The short-lived packaging container overrides its normal app user to read that root-only stage;
the service keeps a private `/tmp`. It relies on the instance role rather than copied AWS keys.
Install a root-only
`/etc/proposal-ingest/backup.env` containing the deploy directory, environment-file path, and
`s3://<private-bucket>/backups` URI, then enable the daily timer:

```bash
sudo bash deploy/install_backup_timer.sh /opt/proposal-ingest
sudo systemctl start proposal-ingest-backup.service
sudo systemctl status proposal-ingest-backup.service
```

The install helper creates a placeholder backup environment file and exits until its URI is set.
The first successful service run is the evidence that the role, PostgreSQL dump, object-volume
read, S3 upload, and versioned destination work together. Preserve a recent backup outside the
host before any recovery or host replacement. Versioned S3 objects are not a substitute for a
restore drill. CloudFormation's `BackupRetentionDays` defaults to 90 days (owner-configurable
from 30 to 3650); lifecycle expiration applies only to the `backups/` prefix and both current and
noncurrent backup versions. Curated KB objects are outside that prefix and do not expire under
this rule. Review the retention value against the recovery policy before deployment. The daily
timer aims for an RPO of at most 24 hours; systemd does not guarantee completion or alert on a
missed run, so verify the last successful timestamp during operations until monitoring is added.

`scripts/app_recovery.py` supports direct verification, packaging, and restore into a *new empty*
database and empty object directory. It validates the entire manifest and dump/object hashes
before touching the target, checks that the target has no user tables, supplies credentials only
through `PG*` environment variables (never `pg_restore` arguments), uses a single transaction for
database restore, requires `PROPOSAL_PUBLICATION_HOLD=true`, and removes newly copied objects if
database restore fails. Stop web and worker before any in-place recovery attempt; prefer an
isolated host/project, database, and object root. Set the restore process environment to
`PROPOSAL_PUBLICATION_HOLD=true`; the CLI flag alone is insufficient. Example for an isolated PostgreSQL 18 target with PostgreSQL client tools
installed locally:

```bash
python scripts/app_recovery.py verify --bundle /private/backups/<timestamp>
PROPOSAL_PUBLICATION_HOLD=true python scripts/app_recovery.py restore \
  --database-url "$RECOVERY_DATABASE_URL" \
  --bundle /private/backups/<timestamp> \
  --object-root /private/recovery/objects \
  --publication-hold
```

Restore PostgreSQL into a database created specifically for recovery; never pass the live
production database or nonempty object directory. The command does not issue `DROP`, `--clean`,
or overwrite operations. Keep publication held until identity/source/decision state has been
reviewed. The local retrieval path is rebuilt from restored database publication mappings and
verified immutable object bytes; inspect saved citation locators before resuming use.

The separate live Managed KB restore requires re-upload/re-ingestion and exact per-document
reconciliation while the application hold rejects retrieval. The held
`reconcile_publication --reindex-active` path prepares the restored active generation, reuploads
and verifies its exact artifacts, and requires explicit held activation. Follow
[the recovery reindex procedure](MVP-08-REINDEX.md). This offline implementation does not prove
live Managed KB behavior; acceptance 08-E remains pending until the isolated one-family restore
and timing drill are recorded.

## Verification and remaining work

Offline files added for 08-A include the runtime lock, image, production Compose/Caddy config,
TLS setup, CloudFormation definition, SSM environment renderer, database/object backup packer,
restore verifier, and daily backup timer. Unit tests use synthetic bytes and do not require
PostgreSQL or AWS. Live IAM behavior, AMI package availability, Caddy certificate issuance, TLS
mount permissions on the target host, model/KB API permissions, actual costs, Entra, SharePoint,
and restore timings remain unverified. Measure host resource/cost behavior before accepting the
`t3.small` default; the single-host stack accepts downtime and is not a high-availability design.
