"""Normalize near-miss model output values before schema validation."""

from __future__ import annotations

import json
import re
from typing import Any

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

_ENUM_ALIASES: dict[tuple[str, ...], dict[str, str]] = {
    ("document_identity", "document_category"): {
        "budget": "budget_financial",
        "budget_spreadsheet": "budget_financial",
        "opportunity_source": "opportunity_document",
    },
    ("document_identity", "document_role"): {
        "budget_spreadsheet": "budget",
        "partner_support_letter": "letter_of_support",
        "support_letter": "letter_of_support",
        "foa_instructions": "submission_instructions",
    },
    ("document_identity", "origin_type"): {
        "generated": "generated_response",
        "generated_by_team": "generated_response",
        "generated_internal": "generated_response",
        "partner_generated": "generated_response",
        "federal_agency": "source_opportunity",
        "opportunity_source": "source_opportunity",
    },
    ("opportunity_treatment", "recommended_rag_treatment"): {
        "full_ingest": "full_document",
        "full_text": "full_document",
        "metadata": "metadata_only",
        "summary": "summary_only",
    },
    ("proposal_context", "status"): {
        "pre_submission": "drafted",
        "in_progress": "active",
        "under_review": "pending",
    },
}


def normalize_metadata_output(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of model output with common enum aliases canonicalized."""
    normalized = json.loads(json.dumps(data))
    for path, mapping in _ENUM_ALIASES.items():
        current = _get_nested(normalized, path)
        if not isinstance(current, str):
            continue
        alias = mapping.get(_canonical_token(current))
        if alias is not None:
            _set_nested(normalized, path, alias)

    _normalize_program(normalized)
    return normalized


def _normalize_program(payload: dict[str, Any]) -> None:
    path = ("proposal_context", "program")
    current = _get_nested(payload, path)
    if not isinstance(current, str):
        return
    token = _canonical_token(current)
    if token.startswith("sbir"):
        _set_nested(payload, path, "SBIR")
    elif token.startswith("sttr"):
        _set_nested(payload, path, "STTR")
    elif token.startswith("foa"):
        _set_nested(payload, path, "FOA")
    elif token.startswith("baa"):
        _set_nested(payload, path, "BAA")


def _canonical_token(value: str) -> str:
    return _NON_ALNUM_RE.sub("_", value.strip().lower()).strip("_")


def _get_nested(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _set_nested(payload: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    current = payload
    for key in path[:-1]:
        next_value = current.setdefault(key, {})
        if not isinstance(next_value, dict):
            next_value = {}
            current[key] = next_value
        current = next_value
    current[path[-1]] = value
