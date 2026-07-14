"""Deterministic quality-benchmark comparison helpers (issue #9).

Shared by the ``evaluate-quality`` CLI command and
``tests/test_end_to_end_quality.py`` so both compare a synthesized
``ProposalMetadata`` record against the same machine-readable
expected-outcome fixtures the same way. Expected-outcome fixtures are kept
intentionally small and structural (status fields, question-count ceilings,
authoritative/excluded document roles) rather than exact-prose comparisons,
so they hold up against both mock and real-Bedrock synthesis.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from proposal_ingest.schemas import ProposalMetadata


def load_expected_outcomes(path: Path) -> dict[str, dict[str, Any]]:
    """Load expected-outcome fixtures keyed by ``proposal_branch``.

    Each fixture is a JSON file; ``proposal_branch`` inside the payload
    takes precedence, falling back to the filename stem so simple
    ``<branch>.json`` fixtures need not repeat it.
    """
    outcomes: dict[str, dict[str, Any]] = {}
    for fixture_path in sorted(Path(path).glob("*.json")):
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        branch = payload.get("proposal_branch", fixture_path.stem)
        outcomes[branch] = payload
    return outcomes


def evaluate_expected_outcomes(
    proposal: ProposalMetadata,
    *,
    question_count: int,
    expected: dict[str, Any],
) -> list[str]:
    """Compare one synthesized proposal against its expected outcome.

    Returns a list of human-readable mismatch descriptions; an empty list
    means the proposal matches every assertion the fixture makes.
    """
    mismatches: list[str] = []
    actual: dict[str, Any] = {
        "status": str(proposal.canonical_identity.status),
        "award_status": proposal.canonical_identity.award_status,
        "agency": str(proposal.canonical_identity.agency),
        "program": str(proposal.canonical_identity.program),
        "question_count": question_count,
        "document_count": proposal.document_count,
    }

    for field, expected_value in expected.get("fields", {}).items():
        if field not in actual:
            continue
        if actual[field] != expected_value:
            mismatches.append(f"{field}: expected {expected_value!r}, got {actual[field]!r}")

    max_question_count = expected.get("max_question_count")
    if max_question_count is not None and question_count > max_question_count:
        mismatches.append(
            f"question_count {question_count} exceeds max_question_count {max_question_count}"
        )

    authoritative_roles = expected.get("authoritative_document_roles")
    if authoritative_roles is not None:
        actual_roles = sorted(
            {str(e.document_role) for e in proposal.document_lineage if e.is_authoritative}
        )
        if actual_roles != sorted(authoritative_roles):
            mismatches.append(
                f"authoritative_document_roles: expected {sorted(authoritative_roles)}, "
                f"got {actual_roles}"
            )

    excluded_from_rag_roles = expected.get("excluded_from_rag_document_roles")
    if excluded_from_rag_roles is not None:
        excluded_ids = {
            t.document_id
            for t in proposal.knowledge_base_treatment
            if str(t.recommended_rag_treatment) == "exclude"
        }
        actual_excluded_roles = sorted(
            {
                str(entry.document_role)
                for entry in proposal.document_lineage
                if entry.document_id in excluded_ids
            }
        )
        if actual_excluded_roles != sorted(excluded_from_rag_roles):
            mismatches.append(
                "excluded_from_rag_document_roles: expected "
                f"{sorted(excluded_from_rag_roles)}, got {actual_excluded_roles}"
            )

    return mismatches
