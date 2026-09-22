---
description: "Use when implementing a new phase of the proposal-ingest pipeline: replacing CLI stubs, wiring modules, writing phase tests."
applyTo: "src/proposal_ingest/**/*.py,tests/**/*.py"
---

# Implementing proposal-ingest changes

The prototype phase plan in `docs/10_implementation_plan.md` is historical. For product work, read
the selected MVP card in [docs/mvp/PR_PLAYBOOK.md](../../docs/mvp/PR_PLAYBOOK.md), the setup
checklist, and the acceptance matrix. Do not use an old prototype phase number to select new scope.

## Phase Implementation Checklist

1. **Read the active card first** — reconcile it with current code and preserve unrelated changes.
2. **Respect the boundary** — do not create later application modules or placeholder commands.
3. **Wire `--mock-bedrock`** — any command that touches Bedrock must accept and honor `--mock-bedrock` before testing.
4. **Add tests** — use documented synthetic fixtures and no real AWS calls in ordinary tests.
5. **Run `make check`** — all of lint, mypy, and pytest must pass.
6. **Report acceptance evidence** — map each selected MVP acceptance ID to passed, failed, or pending live connection evidence.

## Module Boundaries

- Keep Bedrock calls isolated in `bedrock_client.py` / `mock_bedrock.py` — no `boto3` calls elsewhere.
- Keep file I/O isolated from business logic — scanners/builders should receive paths, not open files themselves where possible.
- `config.py` is the only place that reads `default_config.yaml` and `.env`; pass config down, don't import it deep in modules.

## Output Path Pattern

All output goes under `{output_root}/logs/run_{YYYYMMDD_HHMMSS}_{short_id}/`. Never derive output paths from `source_root`.

Keep private proposals, excerpts, screenshots, evaluations, prompts, responses, and credentials out
of Git, CodeRabbit, and public PR comments. See `docs/mvp/FIXTURE_AND_DATA_POLICY.md`.

## Mock Bedrock Contract

`mock_bedrock.py` must return deterministic, schema-valid metadata regardless of input. Tests that exercise AI paths must use `--mock-bedrock` (or pass the mock function directly). Do not call real Bedrock in tests.
