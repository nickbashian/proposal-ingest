"""Wrap Amazon Bedrock Runtime calls behind a small, testable interface."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import boto3
from pydantic import BaseModel

from proposal_ingest.config import RuntimeConfig
from proposal_ingest.logging_utils import get_logger
from proposal_ingest.prompts import load_smoke_test_prompt

logger = get_logger("bedrock_client")

# Document formats accepted by the Bedrock Converse DocumentBlock.
# Maps file extension (with leading dot) to the Bedrock format string.
BEDROCK_DOCUMENT_FORMATS: dict[str, str] = {
    ".pdf": "pdf",
    ".csv": "csv",
    ".doc": "doc",
    ".docx": "docx",
    ".xls": "xls",
    ".xlsx": "xlsx",
    ".html": "html",
    ".txt": "txt",
    ".md": "md",
}

_BEDROCK_DOC_NAME_DISALLOWED_RE = re.compile(r"[^A-Za-z0-9\-\(\)\[\] ]+")
_BEDROCK_DOC_NAME_WHITESPACE_RE = re.compile(r"\s+")
_DAILY_TOKEN_LIMIT_MARKERS = (
    "too many tokens per day",
    "tokens per day",
    "daily token",
)


class BedrockSmokeTestResult(BaseModel):
    """Structured result for the CLI Bedrock smoke test."""

    model_id: str
    model_label: str
    region: str
    response_text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


def sanitize_bedrock_document_name(filename: str) -> str:
    """Return a Bedrock-safe document name derived from the original filename.

    Bedrock validates the DocumentBlock ``name`` separately from the document
    format, so we strip the extension and keep only the characters allowed by
    the Converse API.
    """
    stem = Path(filename).stem.strip() or "document"
    sanitized = _BEDROCK_DOC_NAME_DISALLOWED_RE.sub(" ", stem)
    sanitized = _BEDROCK_DOC_NAME_WHITESPACE_RE.sub(" ", sanitized).strip()
    return sanitized or "document"


def is_daily_bedrock_token_limit_error(error_message: str | None) -> bool:
    """Return True for Bedrock daily token quota errors that should pause a run."""
    if not error_message:
        return False
    normalized = error_message.lower()
    return "throttlingexception" in normalized and any(
        marker in normalized for marker in _DAILY_TOKEN_LIMIT_MARKERS
    )


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
    prompt: str | None = None,
) -> BedrockSmokeTestResult:
    """Send a minimal text-only Converse request to validate Bedrock access."""
    prompt = prompt if prompt is not None else load_smoke_test_prompt()
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


def call_converse_with_document(
    client: Any,
    *,
    model_id: str,
    system_prompt: str,
    user_prompt: str,
    file_bytes: bytes,
    doc_format: str,
    doc_name: str,
    max_tokens: int,
    temperature: float,
) -> tuple[str, dict[str, Any]]:
    """Send a document to Bedrock via DocumentBlock and return (response_text, usage_dict).

    The ``usage_dict`` contains the raw ``usage`` sub-dict from the Converse response
    (keys: ``inputTokens``, ``outputTokens``, ``totalTokens``).
    """
    logger.debug(
        "call_converse_with_document model_id=%s doc_format=%s doc_name=%s",
        model_id,
        doc_format,
        doc_name,
    )
    safe_doc_name = sanitize_bedrock_document_name(doc_name)
    response = client.converse(
        modelId=model_id,
        system=[{"text": system_prompt}],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "document": {
                            "format": doc_format,
                            "name": safe_doc_name,
                            "source": {"bytes": file_bytes},
                        }
                    },
                    {"text": user_prompt},
                ],
            }
        ],
        inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
    )
    usage: dict[str, Any] = response.get("usage", {})
    return _extract_text_from_converse_response(response), usage


def call_converse_with_text(
    client: Any,
    *,
    model_id: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
) -> tuple[str, dict[str, Any]]:
    """Send a text-only Converse request and return (response_text, usage_dict).

    Used when the document content has been extracted locally and is passed as
    part of the user prompt text rather than as a DocumentBlock.
    """
    logger.debug("call_converse_with_text model_id=%s", model_id)
    response = client.converse(
        modelId=model_id,
        system=[{"text": system_prompt}],
        messages=[
            {
                "role": "user",
                "content": [{"text": user_prompt}],
            }
        ],
        inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
    )
    usage: dict[str, Any] = response.get("usage", {})
    return _extract_text_from_converse_response(response), usage
