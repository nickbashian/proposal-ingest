# MVP-08 connection preflight

`python scripts/connection_preflight.py` checks local environment configuration for the MVP-08
connection session. It reads `.env` and process environment variables, with process environment
values taking precedence. Use `--env-file PATH` to inspect a different private file. It only checks
whether required values are present; it never prints values, calls providers, changes configuration,
or writes files. A nonzero exit status means at least one configuration group needs attention.

The report covers the application database, AWS identity and region, Bedrock model/profile IDs,
per-call estimate and reservation setting presence, publication settings,
web sign-in through Entra OIDC, and the separate read-only SharePoint connector. It shows specific
missing variable names and next actions. Configured status does not prove that credentials work, that
permissions are granted, or that services are enabled.

The application currently stores immutable snapshots on a durable local volume with off-host
backups. Selecting `PROPOSAL_STORAGE_BACKEND=s3` is flagged as needing implementation because the
application's snapshot paths are not wired to an S3 storage adapter.

## Explicit live checks

Run these only during the approved connection session, after setting the intended profile and region.
The AWS commands discard response bodies so account IDs and resource identifiers are not printed:

```powershell
aws sts get-caller-identity --profile $env:AWS_PROFILE > $null
if ($LASTEXITCODE -ne 0) { throw 'AWS identity probe failed' }

aws bedrock list-foundation-models --region $env:AWS_REGION > $null
if ($LASTEXITCODE -ne 0) { throw 'Bedrock API probe failed' }

aws bedrock-agent list-knowledge-bases --region $env:AWS_REGION > $null
if ($LASTEXITCODE -ne 0) { throw 'Managed KB API probe failed' }
```

These API probes establish only identity/API reachability. They do not validate model invocation,
quotas, costs, or the create/ingest/query/delete lifecycle. Validate Entra sign-in and SharePoint
selected-site access with the application's scoped connector flow during the same approved session;
do not print access tokens or raw provider responses. No live probe is run by the preflight command.
