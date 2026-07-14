"""Durable human-override records and shared proposal/document field-patch logic.

Question arbitration (``question_arbiter.py``) and answer application
(``question_loop.py``) both need to translate one canonical field key (for
example ``award_status``) into the corresponding path on a
``ProposalMetadata`` record and, where the field is also carried on
individual documents, the matching ``DocumentMetadata`` path. Proposal
synthesis (``proposal_synthesizer.py``) needs to replay a previously applied
answer onto a freshly (re)synthesized proposal record so a later
deterministic or Bedrock resynthesis never silently overwrites a human
decision. All three concerns share one field map, so it lives here as the
single source of truth.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from proposal_ingest.schemas import (
    Agency,
    DocumentMetadata,
    HumanOverrideRecord,
    Program,
    ProposalMetadata,
    ProposalStatus,
    RagPriority,
    RecommendedRagTreatment,
    UnresolvedDecisionType,
    VersionStatus,
)

HUMAN_OVERRIDES_FILENAME = "human_overrides.jsonl"


@dataclass(frozen=True)
class ProposalFieldSpec:
    """Where one canonical field lives on the proposal record and (optionally) on documents."""

    proposal_path: tuple[str, ...] | None
    document_path: tuple[str, ...] | None
    enum_cls: type | None = None
    is_list: bool = False
    is_numeric: bool = False


PROPOSAL_FIELD_MAP: dict[str, ProposalFieldSpec] = {
    "canonical_proposal_name": ProposalFieldSpec(
        ("canonical_identity", "proposal_name"), ("proposal_context", "canonical_proposal_name")
    ),
    "proposal_name": ProposalFieldSpec(
        ("canonical_identity", "proposal_name"), ("proposal_context", "canonical_proposal_name")
    ),
    "proposal_short_name": ProposalFieldSpec(
        ("canonical_identity", "proposal_short_name"), ("proposal_context", "proposal_short_name")
    ),
    "agency": ProposalFieldSpec(
        ("canonical_identity", "agency"), ("proposal_context", "agency"), enum_cls=Agency
    ),
    "agency_subunit": ProposalFieldSpec(
        ("canonical_identity", "agency_subunit"), ("proposal_context", "agency_subunit")
    ),
    "program": ProposalFieldSpec(
        ("canonical_identity", "program"), ("proposal_context", "program"), enum_cls=Program
    ),
    "phase": ProposalFieldSpec(("canonical_identity", "phase"), ("proposal_context", "phase")),
    "topic_number": ProposalFieldSpec(
        ("canonical_identity", "topic_number"), ("proposal_context", "topic_number")
    ),
    "topic_title": ProposalFieldSpec(
        ("canonical_identity", "topic_title"), ("proposal_context", "topic_title")
    ),
    "solicitation_number": ProposalFieldSpec(
        ("canonical_identity", "solicitation_number"), ("proposal_context", "solicitation_number")
    ),
    "submission_date": ProposalFieldSpec(
        ("canonical_identity", "submission_date"), ("proposal_context", "submission_date")
    ),
    "selection_notification_date": ProposalFieldSpec(
        ("canonical_identity", "selection_notification_date"), None
    ),
    "award_date": ProposalFieldSpec(("canonical_identity", "award_date"), None),
    "status": ProposalFieldSpec(
        ("canonical_identity", "status"), ("proposal_context", "status"), enum_cls=ProposalStatus
    ),
    "award_status": ProposalFieldSpec(
        ("canonical_identity", "award_status"), ("proposal_context", "award_status")
    ),
    "award_amount": ProposalFieldSpec(
        ("canonical_identity", "award_amount"),
        ("proposal_context", "award_amount"),
        is_numeric=True,
    ),
    "lead_organization": ProposalFieldSpec(
        ("organizations", "lead_organization"), ("proposal_context", "lead_organization")
    ),
    "prime_or_sub": ProposalFieldSpec(
        ("organizations", "prime_or_sub"), ("proposal_context", "prime_or_sub")
    ),
    "customer_or_sponsor": ProposalFieldSpec(
        ("organizations", "customer_or_sponsor"), ("proposal_context", "customer_or_sponsor")
    ),
    "partners": ProposalFieldSpec(
        ("organizations", "partners"), ("proposal_context", "partners"), is_list=True
    ),
    "version_status": ProposalFieldSpec(
        None, ("document_identity", "version_status"), enum_cls=VersionStatus
    ),
    "sensitivity_labels": ProposalFieldSpec(
        None, ("sensitivity", "sensitivity_labels"), is_list=True
    ),
    "recommended_rag_treatment": ProposalFieldSpec(
        None,
        ("opportunity_treatment", "recommended_rag_treatment"),
        enum_cls=RecommendedRagTreatment,
    ),
    "rag_priority": ProposalFieldSpec(None, ("inclusion", "rag_priority"), enum_cls=RagPriority),
}

# Fields whose applied value should also patch the matching per-document
# entries in ProposalMetadata.knowledge_base_treatment (keyed by document_id).
KNOWLEDGE_BASE_TREATMENT_FIELDS = frozenset({"recommended_rag_treatment", "rag_priority"})


def canonical_field_key(field: str) -> str:
    """Return the last dotted segment of a field path, lowercased, as its canonical key."""
    return field.rsplit(".", 1)[-1].strip().lower()


def output_root_from_run_dir(run_dir: Path) -> Path:
    """Return the output_root for a run_dir shaped like ``output_root/logs/run_xxx``."""
    return Path(run_dir).parent.parent


def human_overrides_path(output_root: Path) -> Path:
    return Path(output_root) / "review" / HUMAN_OVERRIDES_FILENAME


def load_human_overrides(output_root: Path) -> list[HumanOverrideRecord]:
    """Load all durable human-override records recorded across every past run."""
    path = human_overrides_path(output_root)
    if not path.exists():
        return []
    records: list[HumanOverrideRecord] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            records.append(HumanOverrideRecord.model_validate_json(line))
    return records


def append_human_override(output_root: Path, record: HumanOverrideRecord) -> Path:
    """Append one durable human-override record for future-run replay."""
    path = human_overrides_path(output_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.model_dump(mode="json"), sort_keys=True))
        handle.write("\n")
    return path


def coerce_field_value(spec: ProposalFieldSpec, raw_answer: str) -> Any:
    """Validate/coerce a raw CSV answer against a proposal field's expected shape."""
    if spec.enum_cls is not None:
        valid_values = {item.value for item in spec.enum_cls}  # type: ignore[attr-defined]
        if raw_answer not in valid_values:
            raise ValueError(f"Invalid value: {raw_answer}. Expected one of {sorted(valid_values)}")
        return raw_answer
    if spec.is_list:
        if raw_answer.strip().startswith("["):
            loaded = json.loads(raw_answer)
            if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
                raise ValueError("List answers must be a JSON list of strings")
            return loaded
        return [item.strip() for item in raw_answer.replace("|", ",").split(",") if item.strip()]
    if spec.is_numeric:
        try:
            return float(raw_answer)
        except ValueError as exc:
            raise ValueError(f"Invalid numeric answer: {raw_answer}") from exc
    return raw_answer


def get_value_at_path(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def set_value_at_path(data: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    target = data
    for key in path[:-1]:
        next_value = target.setdefault(key, {})
        if not isinstance(next_value, dict):
            raise ValueError(f"Cannot patch through non-object path component: {key}")
        target = next_value
    target[path[-1]] = value


def apply_knowledge_base_treatment_update(
    proposal_data: dict[str, Any],
    *,
    field_key: str,
    value: Any,
    affected_document_ids: list[str],
) -> None:
    """Patch matching ``knowledge_base_treatment`` entries for the affected documents."""
    entries = proposal_data.get("knowledge_base_treatment")
    if not isinstance(entries, list):
        return
    for entry in entries:
        if isinstance(entry, dict) and entry.get("document_id") in affected_document_ids:
            entry[field_key] = value


def apply_authoritative_document_override(
    proposal_data: dict[str, Any],
    *,
    chosen_document_id: str,
    affected_document_ids: list[str],
) -> None:
    """Reassign document_lineage authority to the human-chosen document."""
    lineage = proposal_data.get("document_lineage")
    if not isinstance(lineage, list):
        return
    for entry in lineage:
        if not isinstance(entry, dict) or entry.get("document_id") not in affected_document_ids:
            continue
        if entry.get("document_id") == chosen_document_id:
            entry["authority_rank"] = "authoritative"
            entry["is_authoritative"] = True
            entry["superseded_by_document_id"] = None
        elif entry.get("authority_rank") != "excluded":
            entry["authority_rank"] = "supporting"
            entry["is_authoritative"] = False
            entry["superseded_by_document_id"] = chosen_document_id


def clear_matching_uncertainties(doc_data: dict[str, Any], field: str) -> None:
    """Remove uncertainty entries on a document matching a just-resolved canonical field."""
    key = canonical_field_key(field)
    uncertainties = doc_data.get("uncertainties")
    if not isinstance(uncertainties, list):
        return
    doc_data["uncertainties"] = [
        item
        for item in uncertainties
        if not (isinstance(item, dict) and canonical_field_key(str(item.get("field", ""))) == key)
    ]


def reapply_overrides_to_proposal(
    proposal: ProposalMetadata, overrides: list[HumanOverrideRecord]
) -> ProposalMetadata:
    """Replay durable human overrides onto a freshly (re)synthesized proposal record.

    Only the resolved scalar value is reapplied here; ``unresolved_decisions``
    is left exactly as freshly computed so the arbiter can still tell the
    difference between "new evidence agrees with the applied answer" (stays
    suppressed) and "new evidence conflicts with it" (reopens the question).
    """
    if not overrides:
        return proposal
    data = proposal.model_dump(mode="json")
    for override in overrides:
        if override.decision_type == UnresolvedDecisionType.authoritative_document.value:
            if isinstance(override.applied_value, str):
                apply_authoritative_document_override(
                    data,
                    chosen_document_id=override.applied_value,
                    affected_document_ids=list(override.affected_document_ids),
                )
            continue
        field_key = canonical_field_key(override.field)
        if field_key in KNOWLEDGE_BASE_TREATMENT_FIELDS:
            apply_knowledge_base_treatment_update(
                data,
                field_key=field_key,
                value=override.applied_value,
                affected_document_ids=list(override.affected_document_ids),
            )
        spec = PROPOSAL_FIELD_MAP.get(field_key)
        if spec is None or spec.proposal_path is None:
            continue
        set_value_at_path(data, spec.proposal_path, override.applied_value)
    return ProposalMetadata.model_validate(data)


def reapply_overrides_to_documents(
    documents: list[DocumentMetadata], overrides: list[HumanOverrideRecord]
) -> list[DocumentMetadata]:
    """Replay durable human overrides onto freshly (re)analyzed document records.

    Deliberately does not touch ``uncertainties``: a freshly analyzed
    document's own uncertainty entry (if any) is the signal the arbiter
    needs to decide whether new evidence still agrees with the applied
    answer or genuinely conflicts with it.
    """
    if not overrides:
        return documents
    overrides_by_document: dict[str, list[HumanOverrideRecord]] = {}
    for override in overrides:
        if override.decision_type == UnresolvedDecisionType.authoritative_document.value:
            continue
        spec = PROPOSAL_FIELD_MAP.get(canonical_field_key(override.field))
        if spec is None or spec.document_path is None:
            continue
        for document_id in override.affected_document_ids:
            overrides_by_document.setdefault(document_id, []).append(override)

    if not overrides_by_document:
        return documents

    updated: list[DocumentMetadata] = []
    for document in documents:
        applicable = overrides_by_document.get(document.document_id)
        if not applicable:
            updated.append(document)
            continue
        data = document.model_dump(mode="json")
        for override in applicable:
            spec = PROPOSAL_FIELD_MAP[canonical_field_key(override.field)]
            assert spec.document_path is not None
            set_value_at_path(data, spec.document_path, override.applied_value)
        updated.append(DocumentMetadata.model_validate(data))
    return updated
