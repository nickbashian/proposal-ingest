---
description: "Use when implementing a new phase of the proposal-ingest pipeline: replacing CLI stubs, wiring modules, writing phase tests."
applyTo: "src/proposal_ingest/**/*.py,tests/**/*.py"
---

# Implementing a Pipeline Phase

Before writing any code for a new phase, read the acceptance criteria in [docs/10_implementation_plan.md](../../docs/10_implementation_plan.md).

## Phase Implementation Checklist

1. **Read the spec first** — check `docs/0N_*.md` for the relevant phase detail and I/O contracts.
2. **Replace the stub** — the CLI command for the phase currently prints `[yellow]…: not yet implemented[/yellow]`. Replace it with real logic wired to the module(s) specified for that phase.
3. **Wire `--mock-bedrock`** — any command that touches Bedrock must accept and honor `--mock-bedrock` before testing.
4. **Add tests** — add at least one test in `tests/` using `sample_data/fake_source_root/` and no real AWS calls. Run `pytest` before marking done.
5. **Run `make check`** — all of lint, mypy, and pytest must pass.
6. **Verify acceptance criteria** — run the exact `proposal-ingest` command(s) listed under "Acceptance criteria" in the implementation plan.

## Module Boundaries

- Keep Bedrock calls isolated in `bedrock_client.py` / `mock_bedrock.py` — no `boto3` calls elsewhere.
- Keep file I/O isolated from business logic — scanners/builders should receive paths, not open files themselves where possible.
- `config.py` is the only place that reads `default_config.yaml` and `.env`; pass config down, don't import it deep in modules.

## Output Path Pattern

All output goes under `{output_root}/run_{YYYYMMDD_HHMMSS}_{short_id}/`. Never derive output paths from `source_root`.

## Mock Bedrock Contract

`mock_bedrock.py` must return deterministic, schema-valid metadata regardless of input. Tests that exercise AI paths must use `--mock-bedrock` (or pass the mock function directly). Do not call real Bedrock in tests.
