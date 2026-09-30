# MVP-10 offline expansion preparation

This command inventories a local `2025` directory by listing names, file sizes, and types. It never opens source files, copies them, creates application records, calls SharePoint/AWS, or starts ingestion. Keep its JSON report and observed-cost input under ignored `private_evaluations/` or another private location. The report contains original proposal and relative file names.

```powershell
$env:PYTHONPATH = (Resolve-Path 'src').Path
& .venv/Scripts/python.exe scripts/manage.py plan_year_expansion `
  --year-root 'X:\private-source\2025' `
  --observed-costs 'private_evaluations\observed-costs.json' `
  --max-items 50 --max-cost-usd 10 `
  --output 'private_evaluations\2025-offline-plan.json'
```

Observed-cost JSON has positive `observed_items` and `observed_indexed_bytes`, plus nonnegative USD strings for `observed_accounted_usd`, `observed_monthly_index_usd`, `setup_spent_usd`, and `current_monthly_usd`. Populate these from a recorded live run and billing/usage evidence, including conservative unknown-call charges. The command estimates incremental variable cost per supported item and monthly indexed storage per source byte. These ratios are preliminary: source bytes are not necessarily indexed bytes, extraction failures and model mix may vary, standing infrastructure and taxes need separate review. Compare the reported projected setup and monthly totals with the $500 and $100 ceilings and prepare a more complete cost sheet before requesting expansion approval.

Every discovered item receives a metadata-only disposition. Unsupported and legacy formats remain visible as `inventory_only` or `awaiting_conversion`; supported files are `awaiting_extraction`, not claimed processed. A stray item directly under the year folder or any listing error makes the report incomplete and suppresses batches. The injected listing contract in `expansion_plan.inventory_listed` likewise requires explicit complete year and proposal pagination. It is not connected to a live Graph year listing yet.

The proposal-scoped batch proposal never splits an over-cap proposal; it holds it for a smaller explicitly approved cap or separate handling. Each batch records item and estimated cost caps and an inventory fingerprint checkpoint. The checkpoint is a planning identifier, not a durable processing checkpoint. Any source change requires re-inventory and a new owner-reviewed plan. `ready` stays false until the distinct expansion approval and a real execution gate exist. No batch is run by this command.

Acceptance status: **10-C preliminary offline mechanism only**. A complete real year inventory, observed forecast, held-out validation, and Nicholas's cost/expansion decision are pending. **10-A, 10-B, 10-D, and 10-E are pending**; no held-out evaluation, full-year processing/publication, regression, or restore has been claimed. The MVP-10 playbook requires a draft PR and explicit expansion go/no-go after held-out results and the cost forecast, separate from final merge approval.
