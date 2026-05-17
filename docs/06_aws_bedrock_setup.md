# 06 — AWS and Bedrock Setup

This guide is for a first-time local setup of Amazon Bedrock for this repo.
If you follow it in order, you should end with a working `proposal-ingest bedrock-smoke-test`.

## What this repo expects

Default model label:

```text
opus-4.6
```

Default Bedrock model ID:

```text
us.anthropic.claude-opus-4-6-v1
```

This repo uses the Bedrock inference profile ID for Claude Opus 4.6. The raw foundation model ID `anthropic.claude-opus-4-6-v1` is rejected for on-demand `converse` calls in this account.

Default region:

```text
us-east-1
```

The code loads these values from `config/default_config.yaml`, then lets `.env` and shell environment variables override them.

## Before you start

You need all of the following:

1. An AWS account you can sign into.
2. Permission to use Amazon Bedrock in at least one region.
3. Permission to use an Anthropic Claude model in Bedrock.
4. AWS CLI installed locally.
5. This repo installed in a Python virtual environment.

If you do not control your AWS account, expect one possible blocker: an admin may need to grant Bedrock access or enable a model before any local command can work.

## Step 1 — Install the AWS CLI

If AWS CLI is not installed yet, install version 2.

Windows check:

```powershell
aws --version
```

Expected result is a printed AWS CLI version. If the command is not found, install AWS CLI v2 before continuing.

## Step 2 — Choose how you will authenticate

Use a named profile. Do not hardcode keys in source files.

You usually have one of these paths:

### Option A — AWS SSO or IAM Identity Center

Use this if your company already signs into AWS through a browser flow.

```powershell
aws configure sso --profile proposal-assistant
```

AWS CLI will prompt for:

- SSO start URL
- SSO region
- account
- role
- default region
- output format

After setup, log in:

```powershell
aws sso login --profile proposal-assistant
```

### Option B — Access key profile

Use this only if your AWS administrator explicitly gave you an access key and secret.

```powershell
aws configure --profile proposal-assistant
```

AWS CLI will prompt for:

- AWS access key ID
- AWS secret access key
- default region
- output format

For this repo, use `us-east-1` as the default region unless your team intentionally uses a different Bedrock region.

## Step 3 — Verify the AWS profile works

Before you touch Bedrock, verify that the profile can authenticate.

```powershell
aws sts get-caller-identity --profile proposal-assistant
```

Expected result: a JSON object containing your AWS account ID and ARN.

If this fails, stop here and fix authentication first. Bedrock debugging is wasted effort until `sts get-caller-identity` works.

## Step 4 — Enable Bedrock model access in the AWS Console

This is the step that trips up most first-time users.

1. Sign into AWS Console.
2. Switch to region `us-east-1`.
3. Open Amazon Bedrock.
4. Find the model access page. AWS may label this as `Model access`, `Manage model access`, or similar.
5. Locate Anthropic Claude models.
6. Request or enable access for the Claude model your team wants to use.
7. Complete any Anthropic first-time-use or Marketplace prompts if AWS shows them.

If your company account uses approval workflows, this may require an admin or platform team member.

## Step 5 — Confirm IAM permissions

Your identity needs permission to call the Bedrock runtime.

For a prototype, the safe minimum is usually permission to invoke Bedrock models. Some organizations also grant explicit Converse permissions separately.

Example prototype policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:Converse",
        "bedrock:ConverseStream"
      ],
      "Resource": "*"
    }
  ]
}
```

If your team prefers tighter scoping, restrict `Resource` to the allowed model ARNs instead of `*`.

If you are not sure whether your permissions are the issue, ask your AWS admin this exact question:

```text
Does my profile or role have permission to call Bedrock Runtime Converse for Anthropic Claude in us-east-1?
```

## Step 6 — Configure this repo

Copy the repo env template if you have not done that yet:

```powershell
Copy-Item .env.example .env
```

Then set the Bedrock values in `.env`:

```text
AWS_PROFILE=proposal-assistant
AWS_REGION=us-east-1
BEDROCK_MODEL_LABEL=opus-4.6
BEDROCK_MODEL_ID=us.anthropic.claude-opus-4-6-v1
```

Also set your local paths:

```text
PROPOSAL_INGEST_SOURCE_ROOT=C:\path\to\your\read-only\archive
PROPOSAL_INGEST_OUTPUT_ROOT=C:\path\to\your\output
PROPOSAL_INGEST_TRACKER_PATH=
```

If you prefer not to use `.env`, you can set the shell environment directly.

PowerShell example:

```powershell
$env:AWS_PROFILE="proposal-assistant"
$env:AWS_REGION="us-east-1"
$env:BEDROCK_MODEL_LABEL="opus-4.6"
$env:BEDROCK_MODEL_ID="us.anthropic.claude-opus-4-6-v1"
```

## Step 7 — Install Python dependencies

From the repo root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

## Step 8 — Run the smoke test

This repo now includes a real Bedrock smoke test command.

Run it from the repo root:

```powershell
proposal-ingest bedrock-smoke-test
```

Expected output:

1. The Bedrock model ID being used.
2. The region.
3. A short text response from the model.
4. Token usage when AWS returns it.

Example shape:

```text
Model ID: us.anthropic.claude-opus-4-6-v1
Region: us-east-1
Response: Bedrock connectivity is working.
Usage: input=12 output=7 total=19
```

Real example from a successful local run:

```text
Model ID: us.anthropic.claude-opus-4-6-v1
Region: us-east-1
Response: I'm connected and responding to you via Amazon Bedrock successfully.
Usage: input=19 output=17 total=36
```

If this command succeeds, your Bedrock credentials, region, model access, and repo config are all good enough for the next phase.

## Fast failure checklist

Use this order when the smoke test fails:

1. Run `aws sts get-caller-identity --profile proposal-assistant`.
2. Confirm the AWS Console is set to `us-east-1`.
3. Confirm the Anthropic model is enabled in Bedrock model access.
4. Confirm your role or user has Bedrock runtime permission.
5. Confirm `.env` or shell variables point to the intended profile and region.
6. Re-run `proposal-ingest bedrock-smoke-test`.

## Common failure cases

### `The security token included in the request is invalid`

Your profile is not authenticated.

Fix:

- For SSO: run `aws sso login --profile proposal-assistant` again.
- For access keys: re-run `aws configure --profile proposal-assistant` and verify the credentials.

### `AccessDeniedException`

Your AWS identity authenticated successfully, but it does not have permission to call Bedrock or use the model.

Fix:

- ask your admin for Bedrock runtime permissions
- verify model access is enabled for Anthropic Claude in the selected region

### `ValidationException` or model not found errors

The region or model ID is wrong for your account.

Fix:

- confirm `AWS_REGION=us-east-1`
- confirm `BEDROCK_MODEL_ID=us.anthropic.claude-opus-4-6-v1`
- confirm the model is actually enabled in that region

### `Invocation of model ID ... with on-demand throughput isn’t supported`

You are calling the raw foundation model ID instead of the required inference profile.

Fix:

- use `BEDROCK_MODEL_ID=us.anthropic.claude-opus-4-6-v1`
- or use the full inference profile ARN for that same Bedrock profile
- open a fresh terminal after editing `.env` if your shell still has stale environment variables loaded

### AWS CLI works but `proposal-ingest bedrock-smoke-test` fails

Usually this means the shell environment and the CLI profile do not match.

Fix:

- print your variables in PowerShell:

```powershell
Get-ChildItem Env:AWS_PROFILE
Get-ChildItem Env:AWS_REGION
Get-ChildItem Env:BEDROCK_MODEL_ID
```

- verify they point to the same account and region you tested manually

## Why this repo uses Converse API

The Bedrock wrapper uses the Runtime `converse` API because it gives one message-based interface across supported models and aligns with the repo's prompt-driven document workflow.

## Direct document processing reference

Bedrock `DocumentBlock` supports these document formats:

```text
pdf, csv, doc, docx, xls, xlsx, html, txt, md
```

This matches the MVP supported set except PowerPoint. PowerPoint stays inventory-only unless a PDF equivalent exists.

Conceptual Python example:

```python
import boto3
from pathlib import Path

client = boto3.client("bedrock-runtime", region_name="us-east-1")

file_path = Path("Technical Volume.pdf")
file_bytes = file_path.read_bytes()

response = client.converse(
  modelId="us.anthropic.claude-opus-4-6-v1",
    system=[{"text": system_prompt}],
    messages=[
        {
            "role": "user",
            "content": [
                {"text": user_prompt},
                {
                    "document": {
                        "format": "pdf",
                        "name": "document.pdf",
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

Important detail:

- use a neutral document name in the document block
- keep the real filename in prompt text or metadata, not in the document block `name`

## Mock mode

Mock mode is still required for CI, local testing, and cheap iteration.

Use `--mock-bedrock` or `MOCK_BEDROCK=true` whenever you want to avoid real AWS calls.

## Recommended first real workflow

1. Get `aws sts get-caller-identity` working.
2. Get `proposal-ingest bedrock-smoke-test` working.
3. Run one tiny text file through `process-file` once that command is fully wired.
4. Run one small PDF.
5. Only then try a folder or batch run.
