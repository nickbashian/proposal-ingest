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
        "draft_or_final_evidence": "",
        "language": "unknown",
        "document_date": None,
    },
    "proposal_context": {
        "canonical_proposal_name": "unknown",
        "proposal_short_name": None,
        "agency": "unknown",
        "agency_subunit": None,
        "program": "unknown",
        "phase": None,
        "topic_number": None,
        "topic_title": None,
        "solicitation_number": None,
        "submission_date": None,
        "response_date": None,
        "status": "unknown",
        "award_status": "unknown",
        "award_amount": None,
        "lead_organization": None,
        "prime_or_sub": "unknown",
        "partners": [],
        "customer_or_sponsor": None,
    },
    "content": {
        "summary_short": "",
        "summary_detailed": "",
        "primary_topics": [],
        "technical_keywords": [],
        "technologies": [],
        "applications": [],
        "performance_metrics": [],
        "technical_claims": [],
        "risks": [],
        "milestones": [],
        "deliverables": [],
    },
    "opportunity_treatment": {
        "opportunity_context_useful": False,
        "boilerplate_heavy": False,
        "useful_context_summary": "",
        "boilerplate_summary": "",
        "recommended_rag_treatment": "metadata_only",
    },
    "inclusion": {
        "include_in_clean_set": False,
        "include_in_future_rag": False,
        "rag_priority": "exclude",
        "include_reason": None,
        "exclude_reason": "Set this when both inclusion booleans are false.",
        "recommended_chunking_strategy": None,
    },
    "sensitivity": {
        "sensitivity_labels": [],
        "contains_budget_or_rates": False,
        "contains_personal_info": False,
        "contains_partner_confidential": False,
        "contains_export_control_flags": False,
        "manual_review_required": False,
        "manual_review_reasons": [],
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
    "uncertainties": [],
    "fields_needing_review": [],
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


def load_pass2_system_prompt() -> str:
    """Return the system prompt for Phase 9 contextual review."""
    return _load_prompt("pass2_contextual_review_system.md")


def load_pass2_user_prompt_template() -> str:
    """Return the raw Phase 9 contextual-review user prompt template."""
    return _load_prompt("pass2_contextual_review_user.md")


def load_folder_summary_system_prompt() -> str:
    """Return the system prompt for folder-level narrative summarization."""
    return _load_prompt("folder_metadata_system.md")


def load_folder_summary_user_prompt_template() -> str:
    """Return the raw folder-summary user prompt template."""
    return _load_prompt("folder_metadata_user.md")


def load_smoke_test_prompt() -> str:
    """Return the Bedrock connectivity smoke-test prompt."""
    return _load_prompt("bedrock_smoke_test.md")


def render_folder_summary_user_prompt(
    *,
    proposal_name: str,
    agency: str,
    program: str,
    status: str,
    included_doc_count: int,
    included_document_lines: str,
) -> str:
    """Render the folder-summary user prompt with proposal context substituted."""
    return (
        load_folder_summary_user_prompt_template()
        .replace("{{PROPOSAL_NAME}}", proposal_name)
        .replace("{{AGENCY}}", agency)
        .replace("{{PROGRAM}}", program)
        .replace("{{STATUS}}", status)
        .replace("{{INCLUDED_DOC_COUNT}}", str(included_doc_count))
        .replace("{{INCLUDED_DOCUMENT_LINES}}", included_document_lines)
    )


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


def render_pass2_user_prompt(
    current_metadata_json: str,
    branch_context_json: str,
    extracted_document_text: str,
) -> str:
    """Render the text prompt for contextual pass-2 review."""
    document_text = (
        extracted_document_text.strip() or "(No text could be extracted from this file.)"
    )
    return (
        load_pass2_user_prompt_template()
        .replace("{{CURRENT_PASS1_METADATA_JSON}}", current_metadata_json)
        .replace("{{BRANCH_CONTEXT_JSON}}", branch_context_json)
        .replace("{{DOCUMENT_TEXT}}", document_text)
        .replace("{{DOCUMENT_METADATA_TEMPLATE_JSON}}", _document_metadata_template_json())
    )
