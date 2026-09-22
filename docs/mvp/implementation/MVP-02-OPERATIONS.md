# MVP-02 local product-slice operator guide

MVP-02 demonstrates the complete interaction with synthetic content and zero provider calls. It
uses PostgreSQL, immutable local object storage, the durable application worker, and the same
authenticated services that later adapters extend. Retrieval and drafting are visibly labeled
local and deterministic; this workflow is not evidence of live retrieval or scientific quality.

## Start the demo

From a bootstrapped checkout:

```powershell
make db-up
make app-migrate
make fixture-slice
$env:PROPOSAL_LOCAL_AUTH_ENABLED = 'true'
make app-run
```

Run `make worker` in a second terminal. Open `http://127.0.0.1:8000/login/`, sign in as
`fixture-owner`, and open **Synthetic product slice**. If `make fixture-slice` already enqueued the
import, open its recent job; otherwise select **Import synthetic family**. The worker imports the
fixture and the job page links back to collection review.

The expected walkthrough is:

1. Inspect all three dispositions: one awaiting a decision, one excluded commercial passage, and
   one included voice-only passage.
2. Include the measured-result passage. Publication remains blocked until this choice is recorded.
3. Publish. The excluded passage is never copied into curated bytes. The voice passage is visibly
   marked and cannot appear in factual retrieval or be pinned as factual evidence.
4. Create a writing workspace, search for `capacity 500 cycles`, pin the result, and generate a
   deterministic draft.
5. Open its source link to see the exact saved passage and `section Results, paragraph 2` locator.
6. Edit and regenerate. Revision history retains the edit and the earlier immutable revisions.
7. Export Markdown or text; both formats retain local source links.

Running **Import synthetic family** or **Publish eligible passages** again is idempotent. The
fixture command also reuses its stable job. Run the command with a new development database or a
new collection if a clean first-run demonstration is required; do not use `make db-reset` against
retained data.

## Acceptance and troubleshooting

```powershell
.venv/Scripts/python.exe -m pytest tests/test_mvp02.py --basetemp tmp/pytest-mvp02 -v
make check
```

The browser test drives the actual local server and invokes a separate worker process. The process
test opens a fresh Python process against PostgreSQL and verifies that the decision, evidence
packet, and draft revision remain. No AWS, Entra, SharePoint, S3, Managed KB, or model credential is
needed.

If an import job remains queued, verify the worker is running. A deliberately revoked local fixture
identity is not repaired automatically. Local object bytes default to ignored `tmp/app_storage`;
back them up with PostgreSQL for retained demonstrations.

## Migration and rollback

Migration `0005_local_product_slice` adds item dispositions, passage support roles, factual-evidence
pins, and provenance constraints. Back up retained PostgreSQL and object storage before migrating.
For a development-only rollback with no retained MVP-02 data, stop the app and worker, migrate to
`0004_membership_history`, and run the matching MVP-01 code. Reversing deletes evidence-pin rows
and the new disposition/support fields. To retain a real workflow history, restore a verified
pre-migration backup into a separate database rather than reversing in place. No remote index or
provider resource exists in this card.
