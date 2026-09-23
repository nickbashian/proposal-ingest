# MVP-03 legacy export import

The importer stages historical CLI exports after source sync has captured the corresponding
documents. It never creates inclusion decisions, publication artifacts, or new source identities.
Run the command with an allowlisted user who has access to the existing collection:

```powershell
& '.venv\Scripts\python.exe' scripts/manage.py import_legacy `
  --collection <collection-uuid> --user <username> `
  --inventory <file_inventory.jsonl-or-csv> `
  --metadata <all_document_metadata.jsonl> `
  --answers <questions_to_answer.csv>
```

This is a dry run. Omit `--metadata` or `--answers` if unavailable. Inspect the accepted and
quarantined counts. Add `--commit` to preserve the exact export bytes in immutable local storage
and save the validation report in `LegacyImport.records`; rerunning the same bundle is idempotent.
Use a private output root for these exports. The terminal report contains counts and the bundle
hash only. The database report contains the old-to-new identity map and quarantine reason codes.

Mapping requires the legacy 2025 relative path, proposal membership, and observed SHA-256 to
agree with one existing source version. Duplicate old IDs, changed bytes, and ambiguous matches
stay quarantined. Metadata is retained as historical lineage. An old answer is staged only when
its document scope, proposal, source path, evidence summary, and current source version agree.
Document-level inclusion answers always require current passage-level review because old notes
may describe partial inclusion. Accepted historical answers still do not become application
decisions automatically.

Rollback consists of disabling further imports and restoring the database and object store from
a verified pre-import backup. Existing imported lineage and original exports should be retained
when possible for audit. No source file is modified.
