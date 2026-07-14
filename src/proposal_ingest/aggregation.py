"""Deterministic aggregation helpers shared by folder- and proposal-level synthesis."""

from __future__ import annotations

from collections import Counter

from proposal_ingest.schemas import DocumentRole

# Priority order used when selecting a bounded set of "key documents" for a
# proposal or folder record. Earlier roles win when multiple documents match.
KEY_DOCUMENT_ROLES: list[DocumentRole] = [
    DocumentRole.technical_volume,
    DocumentRole.project_description,
    DocumentRole.statement_of_work,
    DocumentRole.commercialization_plan,
    DocumentRole.budget,
    DocumentRole.budget_justification,
    DocumentRole.abstract,
    DocumentRole.rfp,
    DocumentRole.foa,
    DocumentRole.award_notice,
    DocumentRole.quad_chart,
    DocumentRole.final_report,
    DocumentRole.milestone_report,
]

MAX_KEY_DOCUMENTS = 10


def consensus_str(values: list[str | None], *, fallback: str, ignore: set[str]) -> str:
    candidates = [v for v in values if v and v not in ignore]
    return consensus_value(candidates, default=fallback)


def consensus_enum(values: list[str], *, default: str, ignore: set[str]) -> str:
    candidates = [v for v in values if v not in ignore]
    return consensus_value(candidates, default=default)


def consensus_value(candidates: list[str], *, default: str) -> str:
    if not candidates:
        return default
    counts = Counter(candidates).most_common(2)
    if len(counts) > 1 and counts[0][1] == counts[1][1]:
        return default
    return counts[0][0]


def first_non_none(values: list[str | None]) -> str | None:
    return next((v for v in values if v is not None), None)


def union_lists(lists: list[list[str]]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for items in lists:
        for item in items:
            if item and item not in seen:
                seen.add(item)
                result.append(item)
    return result
