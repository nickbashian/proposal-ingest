# MVP-05b AI ingestion operator guide

Apply migration `0017_classificationresult` after a database backup. It adds operational model results and measured browser review time. Keep prior `DecisionEvent` rows and source snapshots during rollback; do not reverse the migration over retained data.

## Fictional local demonstration

Use the normal PostgreSQL development service and the repository environment. The source fixture is `sample_data/application_slice/2025/Fictional 05b/fictional_source.txt`; ingestion treats this directory as read-only. Run:

```powershell
& '.venv\Scripts\python.exe' scripts/manage.py fixture_ai_ingest
1..6 | ForEach-Object { & '.venv\Scripts\python.exe' scripts/manage.py worker --once }
```

The first command prints the collection UUID and review URL. Open that URL in the authenticated local application. The fixture contains a routine technical passage, contradictory fictional capacity values, a sensitive passage, a voice sample, and an ambiguous status. On a clean database, six classification jobs produce one automatically included unit, one prohibited unit, four pending units, and an uncapped exception set. The test `test_operator_demo_uses_real_capture_extraction_worker_and_review` exercises this exact capture/extraction/worker path and verifies the source bytes remain unchanged. A rerun reuses source and job identities; it does not append duplicate automatic decisions.

For another approved local folder, use `sync_sources --connector local --root <proposal-folder> --year 2025 --proposal <identifier> --collection <uuid> --ingest --mock-bedrock`. The folder must be directly under the named year. Run the worker separately, then inspect the review queue. A successful extraction queues model work automatically in local mode; no AWS call is made. The worker can be stopped and restarted. Job reservations and outcomes persist.

The queue shows discovered files, extracted files, tagged passages, supported non-sensitive denominator, automatic resolutions, included/excluded/pending counts, uncapped exceptions, failed calls, human decisions, recorded review seconds, and estimated remaining effort. Open an issue for its exact source passage and locator. An edit, deferral, rejection, or undo is recorded in the decision ledger; a browser edit rebuilds affected current plans. A human correction outranks automatic treatment. Sensitive material remains prohibited even if a narrower answer requests inclusion. Voice use requires an explicit human edit.

## Live operation and stop conditions

Live classification is opt-in. Set `PROPOSAL_LIVE_CLASSIFICATION_ENABLED=true`, configure a positive `classification_estimate_usd_per_call.baseline`, and set `PROPOSAL_CLASSIFICATION_RUN_CAP_USD` before extraction. The configured run cap must cover the estimated one-call-per-unit batch and cannot exceed `job_limit_usd`. Each job budget is its estimate, so uncertain charged attempts cannot be retried beyond that cap. Global setup and monthly reservations remain in `BudgetAccount` across restarts. Keep the Bedrock route's inference profile and task estimate current. Do not set live opt-in merely to clear a backlog without checking expected cost and source scope.

The live route stores source-backed suggestions and use counts, but **never automatically clears a live private passage** in this revision. Its proposed treatment stays unresolved until MVP-09 source-checked calibration and frozen inclusion/exclusion tests establish an approved policy revision. Disabling live dispatch, exhausting a cap, a provider failure, malformed output, missing confidence, a source change, or a large extraction over the configured job bound leaves a visible critical exception and pending plan. Correct the condition and rerun extraction to schedule the same current version; preserve the old attempt and decision audit. Canceling a job prevents its late completion from applying facts or clearance. Changing source bytes, extraction, model, prompt, schema, or policy revision creates a new fingerprint; old results cannot become the current plan.

MVP-06 owns physical S3/Managed KB publication and reconciliation. The existing local publisher can consume the current plan only after its separate inclusion authorization; test coverage inspects its actual bytes and the resulting drafting evidence packet. A model result alone cannot publish anything.
