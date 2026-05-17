"""Wrap Amazon Bedrock Runtime calls behind a small, testable interface."""

from __future__ import annotations

from typing import Any

import boto3
from pydantic import BaseModel

from proposal_ingest.config import RuntimeConfig
from proposal_ingest.logging_utils import get_logger

DEFAULT_SMOKE_TEST_PROMPT = "Reply with one short sentence confirming Bedrock connectivity."
logger = get_logger("bedrock_client")


class BedrockSmokeTestResult(BaseModel):
    """Structured result for the CLI Bedrock smoke test."""

    model_id: str
    model_label: str
    region: str
    response_text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


def create_bedrock_runtime_client(config: RuntimeConfig) -> Any:
    """Create a Bedrock Runtime client from the configured AWS profile and region."""
    session_kwargs: dict[str, Any] = {}
    if config.aws.profile:
        session_kwargs["profile_name"] = config.aws.profile

    session = boto3.Session(**session_kwargs)
    return session.client("bedrock-runtime", region_name=config.aws.region)


def smoke_test_bedrock(
    config: RuntimeConfig,
    *,
    prompt: str = DEFAULT_SMOKE_TEST_PROMPT,
) -> BedrockSmokeTestResult:
    """Send a minimal text-only Converse request to validate Bedrock access."""
    logger.info(
        "Starting Bedrock smoke test model_id=%s region=%s model_label=%s",
        config.bedrock.model_id,
        config.aws.region,
        config.bedrock.model_label,
    )
    client = create_bedrock_runtime_client(config)

    try:
        response = client.converse(
            modelId=config.bedrock.model_id,
            messages=[
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ],
            inferenceConfig={
                "maxTokens": min(config.bedrock.max_tokens, 128),
                "temperature": config.bedrock.temperature,
            },
        )
    except Exception:
        logger.exception(
            "Bedrock smoke test failed model_id=%s region=%s",
            config.bedrock.model_id,
            config.aws.region,
        )
        raise

    usage = response.get("usage", {})
    result = BedrockSmokeTestResult(
        model_id=config.bedrock.model_id,
        model_label=config.bedrock.model_label,
        region=config.aws.region,
        response_text=_extract_text_from_converse_response(response),
        input_tokens=usage.get("inputTokens"),
        output_tokens=usage.get("outputTokens"),
        total_tokens=usage.get("totalTokens"),
    )
    logger.info(
        (
            "Bedrock smoke test succeeded model_id=%s region=%s "
            "input_tokens=%s output_tokens=%s total_tokens=%s"
        ),
        result.model_id,
        result.region,
        result.input_tokens,
        result.output_tokens,
        result.total_tokens,
    )
    return result


def _extract_text_from_converse_response(response: dict[str, Any]) -> str:
    output = response.get("output", {})
    message = output.get("message", {})
    content = message.get("content", [])

    text_parts = [part.get("text", "") for part in content if isinstance(part, dict)]
    response_text = " ".join(part.strip() for part in text_parts if part.strip())
    return response_text or "<no text returned>"
