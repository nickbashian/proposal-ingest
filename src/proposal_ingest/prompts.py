"""Load and render Bedrock prompt templates from the prompts/ directory."""

from __future__ import annotations

import json
from pathlib import Path

# Prompts directory lives two levels above this file: <repo_root>/prompts/
PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

_DOCUMENT_METADATA_TEMPLATE = {
    "schema_version": "0.1.0",
    "document_id": "pipeline_supplied",
    "proposal_id": "pipeline_supplied",
    "run_id": "pipeline_supplied",
    "system": "pipeline_supplied",
    "document_identity": {
        "canonical_document_title": "unknown",
        "document_category": "unknown",
        "document_role": "unknown",
        "origin_type": "unknown",
        "version_status": "unknown",
    },
    "proposal_context": {
        "canonical_proposal_name": "unknown",
        "agency": "unknown",
        "program": "unknown",
        "status": "unknown",
        "award_status": "unknown",
    },
    "content": {
        "summary_short": "",
        "primary_topics": [],
    },
    "opportunity_treatment": {
        "opportunity_context_useful": False,
        "boilerplate_heavy": False,
        "recommended_rag_treatment": "metadata_only",
    },
    "inclusion": {
        "include_in_clean_set": False,
        "include_in_future_rag": False,
        "rag_priority": "exclude",
        "include_reason": None,
        "exclude_reason": "Set this when both inclusion booleans are false.",
    },
    "sensitivity": {
        "manual_review_required": False,
    },
    "tracker_matching": {
        "tracker_match_status": "not_attempted",
    },
    "confidence": {
        "document_category": 0.0,
        "document_role": 0.0,
        "origin_type": 0.0,
        "version_status": 0.0,
        "canonical_proposal_name": 0.0,
        "agency": 0.0,
        "program": 0.0,
        "status": 0.0,
        "award_status": 0.0,
        "include_in_clean_set": 0.0,
        "include_in_future_rag": 0.0,
        "rag_priority": 0.0,
    },
    "questions_for_user": [],
    "processing_notes": [],
}


def _load_prompt(name: str) -> str:
    """Read a prompt template file and return its contents stripped of surrounding whitespace."""
    path = PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def load_system_prompt() -> str:
    """Return the system prompt for document metadata extraction."""
    return _load_prompt("document_metadata_system.md")


def load_user_prompt_template() -> str:
    """Return the raw user prompt template (contains {{PIPELINE_CONTEXT_JSON}} placeholder)."""
    return _load_prompt("document_metadata_user.md")


def load_repair_prompt_template() -> str:
    """Return the raw repair prompt template."""
    return _load_prompt("document_metadata_repair.md")


def _document_metadata_template_json() -> str:
    """Return a compact JSON template matching the required metadata shape."""
    return json.dumps(_DOCUMENT_METADATA_TEMPLATE, indent=2)


def render_user_prompt(pipeline_context_json: str) -> str:
    """Render the user prompt by substituting the pipeline context JSON."""
    return (
        load_user_prompt_template()
        .replace("{{PIPELINE_CONTEXT_JSON}}", pipeline_context_json)
        .replace("{{DOCUMENT_METADATA_TEMPLATE_JSON}}", _document_metadata_template_json())
    )


def render_repair_prompt(validation_error: str, raw_model_response: str) -> str:
    """Render the repair prompt by substituting the error and prior response."""
    return (
        load_repair_prompt_template()
        .replace("{{VALIDATION_ERROR}}", validation_error)
        .replace("{{RAW_MODEL_RESPONSE}}", raw_model_response)
        .replace("{{DOCUMENT_METADATA_TEMPLATE_JSON}}", _document_metadata_template_json())
    )
