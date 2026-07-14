"""Shared helpers for parsing JSON objects out of raw Bedrock text responses."""

from __future__ import annotations

import json
from typing import Any


def strip_markdown_fences(text: str) -> str:
    """Strip a single leading/trailing Markdown code fence, if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def parse_json_object_response(raw_text: str) -> dict[str, Any]:
    """Extract the first top-level JSON object from a raw model response.

    Tolerates responses wrapped in Markdown code fences or preceded/followed
    by commentary text, which some models emit despite instructions not to.
    """
    decoder = json.JSONDecoder()
    candidates = [raw_text.strip()]

    stripped = strip_markdown_fences(raw_text)
    if stripped != raw_text.strip():
        candidates.insert(0, stripped)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        start = candidate.find("{")
        if start < 0:
            continue
        try:
            parsed, _ = decoder.raw_decode(candidate[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    raise ValueError("Model response did not contain a JSON object")
