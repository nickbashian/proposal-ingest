# Light UI quality-control pass

September 30, 2026. This is a small presentation-only follow-up to MVP-08, not a new MVP card or a live acceptance claim.

## Scope and branch coordination

Isolated branch `codex/mvp-ui-polish`, based on MVP-08 commit `dcae3037b129b83aa64ef2ba750b98ddc7c72b24`. The original checkout and draft PRs #26, #24, and #25 were left unchanged. The UI draft targets the MVP-08 branch to show only this diff. Preserve the existing #26 -> #24 -> #25 merge order; keep this draft unmerged, then retarget it to merged `main` and verify the resulting diff/checks before merging. The MVP-09 harness and MVP-10 planner currently touch none of this pass's files.

## What changed

- Consistent label/control spacing and a responsive evidence-filter grid; narrower page gutters.
- Wide tables scroll inside named, keyboard-focusable regions instead of widening the entire page. Long identifiers wrap; small two-column tables still fit.
- Main landmark, skip link, visible keyboard focus, labeled draft editor and passage-selection checkboxes. The query's accessible name matches its visible label.
- Collection-to-operations and return-to-collection links for operations and drafting. Draft tabs identify the workspace title.
- Evidence classifications use labeled details instead of a raw dictionary; nonempty qualifications stay visible as warnings. Empty search results give a concrete next step.
- The copy button says "Copy draft text" because it copies the editor's current text, including unsaved edits.

No service logic, authorization, publication gates, model routing, schema, migrations, or provider integration changed. Rollback is a revert of these template/test changes; no data rollback is needed.

## Browser inspection

Ran the actual Django app on loopback with a dedicated PostgreSQL database and repository-owned synthetic fixtures. Reused the installed Python environment with this worktree's `src` on `PYTHONPATH`. No private corpus or live provider calls were used.

Inspected desktop (1280 x 900), narrow (390 x 844), and intermediate (768 x 900) layouts. Before the change, the collection widened a 390-pixel viewport to 791 pixels and the query input extended outside its card. Afterward, collection, evidence, operations, and source inspector stayed within the viewport; tables retained their own horizontal scrolling.

| View/flow | Evidence |
|---|---|
| Sign-in and home navigation | Local fixture sign-in, collection links, sign-out control and jobs table inspected |
| Ingestion and review | Imported fixture displayed; included a factual passage and published eligible passages locally |
| Curation | Empty and populated review queues, workload, scoped treatment form, partial-selection checkbox label and audit empty state inspected |
| Source inspection | Extracted-unit page, extraction run, long version/hash values and preserved text inspected |
| Evidence browser | Matching search, no-match guidance, provenance, readable classifications and pinning inspected |
| Drafting | Deterministic generation, warning display, labeled editor, saved revision 2 and exact saved citation verified |
| Operations | Recorded job state, usage and recent-work tables inspected at desktop/narrow widths |
| Keyboard | Skip link moved focus to main; Tab reached the next filter with a visible focus outline |

Screenshots of the final desktop evidence form and narrow evidence/operations layouts are retained with the Codex chat. These contain fictional fixtures only.

Live Microsoft sign-in, Managed KB retrieval, Bedrock latency/errors and production operations were intentionally not exercised. Synthetic browser tests cover queued/running/canceled/failed drafting, revision preservation, clipboard/export and expired-session denial. The existing plain authentication-required response remains outside this template-only pass.

## Verification and bounded review

Final check and review results are recorded in the draft PR. The full Windows `scripts/dev.py check` gate uses synthetic tests and the existing browser smoke. Responsive and skip-link assertions were added to the existing full product-flow browser test at 390, 768 and 1280 pixels.

The initial local CodeRabbit review completed with one trivial finding: remove the query input's redundant `aria-label`. Fixed it and aligned the exact test selector. The initial full check passed 662 tests and found the old copy-button label in the MVP-07 browser test; that selector was updated without weakening assertions. One final full check and one bounded CodeRabbit follow-up cover the resulting code. Further speculative or stylistic review loops are not requested.
