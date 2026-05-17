# 06 — AWS and Bedrock Setup

## Current model assumption

Default model label:

```text
opus-4.6
```

Default Bedrock model ID:

```text
anthropic.claude-opus-4-6-v1
```

Default region:

```text
us-east-1
```

AWS documentation lists Claude Opus 4.6 as active, with Converse support, and gives `anthropic.claude-opus-4-6-v1` as the in-region model ID.

## Local AWS setup recommendation

Use a named AWS profile rather than hardcoding keys.

Option A — standard access key profile:

```bash
aws configure --profile proposal-assistant
```

Option B — SSO profile if your account is set up that way:

```bash
aws configure sso --profile proposal-assistant
```

Then set:

```bash
set AWS_PROFILE=proposal-assistant
set AWS_REGION=us-east-1
```

PowerShell:

```powershell
$env:AWS_PROFILE="proposal-assistant"
$env:AWS_REGION="us-east-1"
```

## Bedrock access checklist

1. Sign into AWS Console.
2. Open Amazon Bedrock.
3. Confirm your region is `us-east-1` unless you intentionally choose another region.
4. Open the model catalog / provider page for Anthropic Claude.
5. Confirm Anthropic first-time-use requirements are completed if prompted.
6. Confirm IAM permissions allow `bedrock:InvokeModel`.
7. Run the local smoke test:

```bash
proposal-ingest bedrock-smoke-test
```

## IAM policy minimum for prototype

For local prototype testing, use a scoped policy that allows Bedrock runtime invocation.

Example concept policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": "*"
    }
  ]
}
```

For Marketplace/model access setup, AWS may require Marketplace subscription permissions and Anthropic first-time-use completion. Do this in the console first to avoid debugging local auth prematurely.

## Why Converse API

Use Bedrock Runtime `converse` because it provides one consistent interface for message-style calls across supported Bedrock models. The code should remain model-ID configurable.

## Direct document processing

Bedrock DocumentBlock supports these document formats:

```text
pdf, csv, doc, docx, xls, xlsx, html, txt, md
```

This matches the MVP supported set except PowerPoint. PowerPoint should remain inventory-only unless a PDF equivalent exists.

## Direct document request shape — conceptual Python

```python
import boto3
from pathlib import Path

client = boto3.client("bedrock-runtime", region_name="us-east-1")

file_path = Path("Technical Volume.pdf")
file_bytes = file_path.read_bytes()

response = client.converse(
    modelId="anthropic.claude-opus-4-6-v1",
    system=[{"text": system_prompt}],
    messages=[
        {
            "role": "user",
            "content": [
                {"text": user_prompt},
                {
                    "document": {
                        "format": "pdf",
                        "name": "document.pdf",  # neutral safe name
                        "source": {"bytes": file_bytes},
                    }
                },
            ],
        }
    ],
    inferenceConfig={
        "maxTokens": 4096,
        "temperature": 0,
    },
)
```

Important implementation detail:

- Use a neutral document name. AWS warns that the `name` field can be vulnerable to prompt injection because the model may interpret it as instructions.
- Preserve the original filename in structured prompt text, not as the DocumentBlock `name`.

## Local extraction request shape

When direct document processing fails or is not preferred:

```python
response = client.converse(
    modelId=model_id,
    system=[{"text": system_prompt}],
    messages=[
        {
            "role": "user",
            "content": [
                {"text": user_prompt_with_extracted_text_and_metadata}
            ],
        }
    ],
    inferenceConfig={"maxTokens": 4096, "temperature": 0},
)
```

## Mock mode

Mock mode is required.

Use cases:

- scanner testing
- clean output testing
- CI tests
- metadata validation tests
- avoiding accidental Bedrock spend

Mock mode should generate plausible metadata from filename/path/extension only and clearly mark:

```json
"generated_by": "mock_bedrock"
```

## Cost/latency controls

MVP controls:

- `--limit N`
- `--process-folder`
- `--process-file`
- `--mock-bedrock`
- `MAX_DIRECT_UPLOAD_MB`
- `SAVE_RAW_MODEL_RESPONSES`
- skip already-processed hashes

## Recommended development sequence for AWS integration

1. Build scanner in mock mode.
2. Build metadata validation in mock mode.
3. Run `bedrock-smoke-test` with text-only prompt.
4. Run `process-file` on one tiny TXT/MD file.
5. Run `process-file` on one small PDF.
6. Run `process-folder` on one small proposal branch.
7. Only then run a larger batch.
