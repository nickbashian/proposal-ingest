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
    _normalize_partners(normalized)
    _normalize_content_string_lists(normalized)
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


def _normalize_partners(payload: dict[str, Any]) -> None:
    path = ("proposal_context", "partners")
    current = _get_nested(payload, path)
    if not isinstance(current, list):
        return

    normalized_partners: list[str] = []
    for item in current:
        partner = _coerce_partner_name(item)
        if partner:
            normalized_partners.append(partner)
    _set_nested(payload, path, normalized_partners)


def _coerce_partner_name(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    if isinstance(value, dict):
        preferred_keys = ("name", "organization", "partner_name", "institution", "company")
        for key in preferred_keys:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        for candidate in value.values():
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return None


def _normalize_content_string_lists(payload: dict[str, Any]) -> None:
    content = payload.get("content")
    if not isinstance(content, dict):
        return

    for field_name in ("risks", "milestones", "deliverables"):
        current = content.get(field_name)
        if not isinstance(current, list):
            continue
        normalized_items = [_coerce_content_list_item(item) for item in current]
        content[field_name] = [item for item in normalized_items if item]


def _coerce_content_list_item(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    if not isinstance(value, dict):
        return None

    text_parts: list[str] = []
    preferred_keys = (
        "milestone",
        "deliverable",
        "risk",
        "name",
        "title",
        "description",
        "date",
    )
    for key in preferred_keys:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            text_parts.append(candidate.strip())
    if text_parts:
        return " - ".join(text_parts)

    fallback_parts = [
        candidate.strip()
        for candidate in value.values()
        if isinstance(candidate, str) and candidate.strip()
    ]
    return " - ".join(fallback_parts) if fallback_parts else None


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
