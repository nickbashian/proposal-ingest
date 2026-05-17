# 05 — CLI and Config Spec

## CLI command summary

```bash
proposal-ingest scan \
  --source-root "C:\path\to\source" \
  --output-root "C:\path\to\output"

proposal-ingest analyze --output-root "C:\path\to\output"

proposal-ingest export-questions --output-root "C:\path\to\output"

proposal-ingest apply-answers --output-root "C:\path\to\output"

proposal-ingest build-folders --output-root "C:\path\to\output"

proposal-ingest build-clean-set --output-root "C:\path\to\output"

proposal-ingest run-all \
  --source-root "C:\path\to\source" \
  --output-root "C:\path\to\output"

proposal-ingest process-folder \
  --source-folder "C:\...\2025\2025 DOD SBIR AF251 Li-ion" \
  --output-root "C:\path\to\output"

proposal-ingest process-file \
  --file "C:\...\Technical Volume.docx" \
  --output-root "C:\path\to\output"

proposal-ingest bedrock-smoke-test
```

## Command behavior

### `scan`

Creates or updates inventory.

Options:

```text
--source-root PATH
--output-root PATH
--tracker-path PATH
--dry-run
--force
--config PATH
```

### `analyze`

Processes eligible files using Bedrock or mock mode.

Options:

```text
--output-root PATH
--model-label opus-4.6
--model-id anthropic.claude-opus-4-6-v1
--mock-bedrock
--max-direct-upload-mb 20
--limit N
--force
--force-pass2
--save-raw-responses
--no-save-raw-responses
--process-powerpoints  # future stub; not active by default
```

### `export-questions`

Writes global review CSV.

Options:

```text
--output-root PATH
--include-low-priority
--max-questions-per-file 5
```

### `apply-answers`

Applies manual answers from CSV.

Options:

```text
--output-root PATH
--questions-csv PATH
--dry-run
```

### `build-folders`

Synthesizes folder metadata and summaries.

Options:

```text
--output-root PATH
--force
--mock-bedrock
```

### `build-clean-set`

Copies included files and writes S3 manifest.

Options:

```text
--output-root PATH
--allow-critical-open
--dry-run
--force
```

### `run-all`

Runs the main pipeline.

Default order:

1. scan
2. analyze
3. export-questions
4. stop if critical questions exist
5. apply-answers if answered CSV exists and requested
6. build-folders
7. build-clean-set

`run-all` should stop before clean-set if critical open questions remain.

### `process-folder`

Convenience command for testing on one proposal branch.

Behavior:

- builds a temporary branch-scoped inventory
- processes only that branch
- writes into normal output root

### `process-file`

Convenience command for prompt/model testing.

Behavior:

- processes a single file
- does not require full source tree
- writes debug metadata and raw response

### `bedrock-smoke-test`

Sends a small text-only request to configured model.

Expected output:

- model ID used
- region
- successful response text
- usage if available

## Environment variables

See `.env.example`.

Required for real Bedrock mode:

```text
AWS_PROFILE=proposal-assistant
AWS_REGION=us-east-1
BEDROCK_MODEL_LABEL=opus-4.6
BEDROCK_MODEL_ID=anthropic.claude-opus-4-6-v1
```

Useful local config:

```text
PROPOSAL_INGEST_SOURCE_ROOT=...
PROPOSAL_INGEST_OUTPUT_ROOT=...
PROPOSAL_INGEST_TRACKER_PATH=...
MAX_DIRECT_UPLOAD_MB=20
SAVE_RAW_MODEL_RESPONSES=true
MOCK_BEDROCK=false
```

## Config precedence

Highest to lowest:

1. CLI arguments
2. environment variables
3. config YAML
4. internal defaults

## Config file example

See `config/default_config.yaml`.

## Logging

Every run writes:

```text
reports/processing_errors.csv
reports/bedrock_usage.csv
logs/pipeline.log
```

Bedrock usage columns:

```text
run_id
document_id
proposal_id
model_id
processing_strategy
pass_number
start_time
end_time
latency_seconds
input_tokens
output_tokens
total_tokens
success
error_type
error_message
```

## Return codes

```text
0 success
1 fatal config/setup error
2 completed with non-fatal file processing errors
3 stopped because critical questions remain
4 Bedrock smoke test failed
```
