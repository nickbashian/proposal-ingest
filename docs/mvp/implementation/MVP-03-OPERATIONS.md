# MVP-03 source sync operator guide

Run migrations after backing up a retained PostgreSQL database and local object storage:

```powershell
make db-up
make app-migrate
```

For local development, point at one proposal folder directly under the `2025` year folder. Use an existing collection UUID:

```powershell
$root = 'C:\path\to\synthetic\2025\Proposal A'
$collection = '<collection-uuid>'
$env:PYTHONPATH = 'src'
$env:DJANGO_SETTINGS_MODULE = 'proposal_app.settings'
& '.venv\Scripts\python.exe' -m django sync_sources --collection $collection --proposal 'Proposal A' --year 2025 --connector local --root $root
```

For SharePoint, configure the separate background identity in environment variables (`ENTRA_TENANT_ID`, `SHAREPOINT_SITE_ID`, `SHAREPOINT_DRIVE_ID`, `SHAREPOINT_CLIENT_ID`, `SHAREPOINT_CLIENT_SECRET`). Give the command one proposal folder drive item ID directly under `2025`:

```powershell
& '.venv\Scripts\python.exe' -m django sync_sources --collection $collection --proposal 'Proposal A' --year 2025 --connector sharepoint --root '<drive-item-id>'
```

The command prints the run ID, state, and counts for seen items, new snapshots, reused snapshots, capture issues, and retired scope memberships. It exits unsuccessfully for an incomplete run. Rerunning resumes a saved page cursor; an expired cursor starts a fresh full enumeration. A clean completed enumeration retires missing items only within that proposal scope. A failed or interrupted crawl retains previous memberships. Each new invocation after completion performs a full scoped delta enumeration, so absence is reconciled from a complete view. The source directory is never written. Source snapshots and import exports live in immutable local object storage configured by `PROPOSAL_LOCAL_STORAGE_ROOT`.

The default maximum snapshot is 50 MiB (`web_application.max_snapshot_bytes`); larger items remain in the inventory with a capture issue and block retirement until handled. ZIP, email, and legacy files are inventoried and snapped but await a later extraction or conversion decision. Administrative files are recorded without copying bytes. Review `SourceCaptureIssue` and `SourcePresence` rows for a failed run; error codes avoid raw provider messages. The Graph client does not retry throttling in a tight loop: rerun later to resume its cursor.

The seed SharePoint connection is intentionally pending MVP-08. Before enabling it, confirm selected-site read permission, the exact drive and folder IDs, scoped delta support, download behavior, and source read-only policy with the tenant administrator. Avoid putting tokens, signed download URLs, or private source paths into PRs or screenshots.
