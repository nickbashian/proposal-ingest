# MVP-07 writing operator guide

Apply migrations 0024 through 0027 with the normal application migration command. These
add saved requests, revision checks, voice pins, source exclusions, generation attempts,
and PostgreSQL reference/ownership guards. Back up the database and immutable local
object store together. Source folders remain read-only.

## Offline rehearsal

From the repository root, with the development PostgreSQL service running:

```powershell
& .venv/Scripts/python.exe scripts/manage.py migrate
& .venv/Scripts/python.exe scripts/manage.py fixture_writing
$env:PROPOSAL_LOCAL_AUTH_ENABLED = "true"
& .venv/Scripts/python.exe scripts/manage.py runserver 127.0.0.1:8000 --noreload
```

Open the local login page and choose the subject `fictional-writing-owner`. The fixture
command prints five writing URLs. All passages, quantities, and claims are invented;
this rehearsal does not establish scientific accuracy or writing usefulness on real data.
Its source JSON is read-only and provenance is recorded in `sample_data/PROVENANCE.md`.
The command is repeatable before the source-update step, retaining existing demo revisions.

The five workspaces demonstrate an outline, prior-results passage, technical section,
conflicting-results comparison, and revision containing a labeled proposed experiment.
Each uses separate human-approved voice selections. The comparison displays a focused
question for contradictory quantities. The last workspace includes an edited revision.
Inspect the exact request and each saved citation from the workspace.

Use the query `FICTIONAL-2025-WRITING` to exercise exact proposal lookup. Browse the
Evidence, Reasoning, Requirements, and Approved voice views. Filters use established
curation labels: proposal, source role, chemistry, temporal meaning, and content use.
Observed dates are source observations, not inferred submission dates or scientific
currency. Unknown labels remain unknown. Equal passages with equal labels collapse
while preserving their locations; different conditions or claim types stay separate.
The factual evidence view includes currently published reasoning/requirements passages.
Original/context/version comparisons are inspection views and do not authorize model use.

Run the source-update step after inspecting the saved prior-results draft:

```powershell
& .venv/Scripts/python.exe scripts/manage.py fixture_writing --update-source
```

Its saved citation still displays the exact old excerpt and marks it historical. The old
pin cannot seed a new request. Curate/publish the new version, select current passages,
and choose the refresh option before regeneration. Do not rerun initial fixture loading
after this step: the old version is deliberately no longer current. Use an isolated fresh
demo database for another full rehearsal rather than deleting retained evidence.

## Routine writing and recovery

Pin factual passages and approved voice independently. Source exclusions apply to the
whole source in this workspace, including voice; they never alter shared collection
curation. A pin cannot override an exclusion, publication hold, retired version, current
policy, or withdrawn decision. Voice prose and numbers cannot serve as factual support.

Enter task, mode, audience, length, and any current assertions. Assertions and proposed
work remain unverified; generated drafts never enter the corpus automatically. Any
promotion must use a separate source/provenance and the existing explicit curation
workflow. The generation request captures the exact factual/voice selections, source
versions, decision revisions, generation identity, locators, prompt/model versions,
prior draft, and user task.

The default background option persists the request and returns immediately. Run the
normal `scripts/manage.py worker` in a second terminal. Refresh the writing page for
queued/running/completed status; closing the page does not discard the request. Cancel
from the workspace. Timed-out/interrupted attempts preserve earlier revisions and require
an explicit retry. No late result can replace an intervening edit or canceled attempt.
Provider failures expose a sanitized reason, not source or provider-response contents.
If a session expires, sign in again and reopen the workspace; saved revisions/attempts
remain available. Browser form errors and stale revisions return a conflict rather than
silently overwriting edits.

Save edits as new revisions. Compare any owned revision with the latest, or restore it
as a new revision. Restore preserves the old packet for historical inspection and keeps
the restored text marked for review. Copy the text or export Markdown/plain text, with
the source appendix checkbox controlling the extra source listing. Exports with unresolved
checks carry a review warning. Only application-owned source/citation destinations are
converted to links; arbitrary links and remote images are removed, and HTML is escaped.

Claim checking is intentionally conservative. Exact unchanged source quotations with
established scientific labels can pass; prose, paraphrases, unsupported quantities,
chemistry/condition terms, unknown citation IDs, unresolved scientific scope, assertions,
and contradictory quantities require review. This is a reuse gate, not an entailment
model or a substitute for Nicholas's scientific check. It may flag compatible quantities
when their relationship is not established. A cited target/requirement is never promoted
to a measured result by style evidence. Saved packet citation URLs are owner private;
original published source artifacts remain shared with authorized collection members.

## Bedrock connection boundary

Default `drafting_backend: local` uses deterministic quotation scaffolds with zero provider
calls. For later live verification, configure `PROPOSAL_DRAFTING_BACKEND=bedrock`,
`PROPOSAL_LIVE_DRAFTING_ENABLED=true`, an appropriate configured inference-profile model
ID, and `PROPOSAL_DRAFTING_RESERVATION_USD` covering the bounded request's worst-case cost.
No default estimate enables paid calls. Verify this estimate against measured input/output
tokens and current pricing before enabling it. Model/output/request/timeout limits live
in configuration. The regular durable job ledger reserves setup/monthly/per-job budget
before dispatch. SDK retries are disabled for the call; unknown outcomes retain the
reservation, and retries are explicit. Token usage is recorded; charged cost is labeled
as a conservative estimate pending billing reconciliation.

The adapter follows the AWS [Converse request contract](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html).
The saved wire request contains the exact system/message/inference arguments dispatched.
No tools are offered and tool blocks, truncated outputs, and malformed responses fail
closed. Application eligibility and ownership are checked before dispatch and again
before revision delivery. Connecting AWS, validating account behavior, live prices,
Entra/SharePoint, deployment, and real writing quality remain MVP-08/09 work.

## Rollback and owner evaluation set

Disable new generation or revert to the local route while retaining the additive schema,
packets, revisions, source snapshots, and artifact mappings. Use the normal publication
hold during restore; never reactivate withdrawn evidence from an older backup. An older
application can read its existing fields with this additive schema; do not reverse the
history guards or delete immutable writing records to roll back code.

Nicholas agreed on September 28, 2026 to record these five proposed real tasks and choose
private examples later: prior-results passage; technical approach outline;
solicitation-compliance section; comparison of conflicting/versioned results; revision
responding to reviewer feedback. Use the three seed families after live connection.
Proposed voice examples: one approved opening, one technical approach paragraph, and one
transition/closing. Source selection and scientific/usefulness acceptance remain pending.
No DOCX export, submission, external chat, public-web product research, or deployment
is part of MVP-07.
