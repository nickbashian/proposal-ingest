"""Build proposal-aware RAG retrieval artifacts and provenance reports (issue #9).

A synthesized ``ProposalMetadata`` record already carries document lineage,
authority ranking, and knowledge-base treatment (issue #7); this module
reshapes that record into the first-class retrieval objects the clean-set
build writes to disk (``retrieval/proposal_context.json``,
``retrieval/document_manifest.jsonl``) and into human-readable provenance
reports that explain *why* the pipeline made those decisions, without
duplicating any source document text.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from proposal_ingest.schemas import (
    BedrockUsageRecord,
    DocumentManifestEntry,
    DocumentMetadata,
    HumanOverrideRecord,
    ManifestObjectType,
    ProposalMetadata,
    ProposalRetrievalRecord,
    RagPriority,
    RagPrioritySummary,
    RecommendedRagTreatment,
    ReviewQuestion,
    SensitivityLabel,
    SensitivitySummary,
)


def build_proposal_retrieval_record(
    proposal: ProposalMetadata,
    documents: list[DocumentMetadata],
) -> ProposalRetrievalRecord:
    """Build the primary RAG retrieval entry point for one proposal.

    References documents and evidence by ``document_id`` (via
    ``document_lineage``, ``key_documents``, ``knowledge_base_treatment``,
    and ``evidence``, all inherited unchanged from ``proposal``) rather than
    duplicating source text.
    """
    documents_by_id = {doc.document_id: doc for doc in documents}

    labels_present: set[SensitivityLabel] = set()
    manual_review_count = 0
    restricted_ids: list[str] = []
    for treatment in proposal.knowledge_base_treatment:
        doc = documents_by_id.get(treatment.document_id)
        if doc is None:
            continue
        labels_present.update(doc.sensitivity.sensitivity_labels)
        if doc.sensitivity.manual_review_required:
            manual_review_count += 1
            restricted_ids.append(doc.document_id)

    priority_counts = Counter(str(t.rag_priority) for t in proposal.knowledge_base_treatment)

    return ProposalRetrievalRecord(
        proposal_id=proposal.proposal_id,
        canonical_identity=proposal.canonical_identity,
        organizations=proposal.organizations,
        proposal_summary=proposal.proposal_summary,
        document_lineage=proposal.document_lineage,
        key_documents=proposal.key_documents,
        knowledge_base_treatment=proposal.knowledge_base_treatment,
        evidence=proposal.evidence,
        unresolved_decisions=proposal.unresolved_decisions,
        sensitivity_summary=SensitivitySummary(
            labels_present=sorted(labels_present),
            manual_review_required_count=manual_review_count,
            restricted_document_ids=sorted(restricted_ids),
        ),
        rag_priority_summary=RagPrioritySummary(
            high=priority_counts.get("high", 0),
            medium=priority_counts.get("medium", 0),
            low=priority_counts.get("low", 0),
            exclude=priority_counts.get("exclude", 0),
        ),
        document_count=proposal.document_count,
    )


def build_document_manifest_rows(
    proposal: ProposalMetadata,
    documents: list[DocumentMetadata],
    *,
    local_clean_paths: dict[str, str] | None = None,
    metadata_paths: dict[str, str] | None = None,
) -> list[DocumentManifestEntry]:
    """Build one proposal-scoped manifest row per document, in lineage order.

    ``local_clean_paths``/``metadata_paths`` are optional document_id-keyed
    lookups of where each document actually landed in the clean-set mirror;
    documents that were excluded (and so were never copied) simply omit
    those paths rather than pointing at a file that does not exist.
    """
    documents_by_id = {doc.document_id: doc for doc in documents}
    treatment_by_id = {t.document_id: t for t in proposal.knowledge_base_treatment}
    local_clean_paths = local_clean_paths or {}
    metadata_paths = metadata_paths or {}

    rows: list[DocumentManifestEntry] = []
    for entry in proposal.document_lineage:
        doc = documents_by_id.get(entry.document_id)
        treatment = treatment_by_id.get(entry.document_id)
        rows.append(
            DocumentManifestEntry(
                document_id=entry.document_id,
                proposal_id=proposal.proposal_id,
                parent_proposal_record=proposal.proposal_id,
                file_name_original=entry.file_name_original,
                document_role=entry.document_role,
                version_status=entry.version_status,
                authority_rank=entry.authority_rank,
                is_authoritative=entry.is_authoritative,
                superseded_by_document_id=entry.superseded_by_document_id,
                contains_unique_reasoning=entry.contains_unique_reasoning,
                rag_priority=treatment.rag_priority if treatment else RagPriority.medium,
                recommended_rag_treatment=(
                    treatment.recommended_rag_treatment
                    if treatment
                    else RecommendedRagTreatment.metadata_only
                ),
                sensitivity_labels=doc.sensitivity.sensitivity_labels if doc else [],
                local_clean_path=local_clean_paths.get(entry.document_id),
                metadata_path=metadata_paths.get(entry.document_id),
            )
        )
    return rows


def build_proposal_provenance_report(
    proposal: ProposalMetadata,
    documents: list[DocumentMetadata],
    *,
    overrides: list[HumanOverrideRecord] | None = None,
) -> dict[str, Any]:
    """Build a compact, human-readable explainability report for one proposal."""
    documents_by_id = {doc.document_id: doc for doc in documents}
    treatment_by_id = {t.document_id: t for t in proposal.knowledge_base_treatment}

    authoritative = [e.document_id for e in proposal.document_lineage if e.is_authoritative]
    retained_low_priority = [
        e.document_id
        for e in proposal.document_lineage
        if not e.is_authoritative and e.contains_unique_reasoning
    ]
    downgraded = [
        e.document_id
        for e in proposal.document_lineage
        if not e.is_authoritative and not e.contains_unique_reasoning
    ]
    excluded = [doc.document_id for doc in documents if not doc.inclusion.include_in_clean_set]

    policies_applied: Counter[str] = Counter()
    exceptions: list[dict[str, str]] = []
    for treatment in proposal.knowledge_base_treatment:
        if treatment.policy_applied:
            policies_applied[treatment.policy_applied] += 1
        if treatment.exception_reason:
            exceptions.append(
                {
                    "document_id": treatment.document_id,
                    "policy_applied": treatment.policy_applied or "",
                    "exception_reason": treatment.exception_reason,
                }
            )

    bedrock_inferences = [
        {
            "document_id": doc.document_id,
            "file_name_original": doc.system.file_name_original,
        }
        for doc in documents
        if "generated_by: mock_bedrock" not in doc.processing_notes
    ]

    applied_overrides = [
        {
            "question_id": o.question_id,
            "field": o.field,
            "applied_value": o.applied_value,
            "timestamp": o.timestamp,
        }
        for o in (overrides or [])
    ]

    return {
        "proposal_id": proposal.proposal_id,
        "proposal_name": proposal.canonical_identity.proposal_name,
        "synthesis_source": proposal.synthesis_source,
        "document_count": proposal.document_count,
        "authoritative_documents": sorted(authoritative),
        "retained_low_priority_documents": sorted(retained_low_priority),
        "downgraded_documents": sorted(downgraded),
        "excluded_documents": sorted(excluded),
        "standing_policies_applied": dict(sorted(policies_applied.items())),
        "policy_exceptions": exceptions,
        "bedrock_inferences_used": bedrock_inferences,
        "human_overrides_applied": applied_overrides,
        "remaining_unresolved_decisions": [
            {
                "field": d.field,
                "decision_type": str(d.decision_type),
                "downstream_impact": str(d.downstream_impact),
                "reason_unresolved": d.reason_unresolved,
            }
            for d in proposal.unresolved_decisions
        ],
        "knowledge_base_treatment_by_document": {
            doc_id: {
                "recommended_rag_treatment": str(t.recommended_rag_treatment),
                "rag_priority": str(t.rag_priority),
            }
            for doc_id, t in treatment_by_id.items()
            if doc_id in documents_by_id
        },
    }


def build_run_provenance_report(
    proposals: list[ProposalMetadata],
    *,
    arbitrated_questions: list[ReviewQuestion],
    suppressed_count: int,
    resolved_by_override_count: int,
    usage_records: list[BedrockUsageRecord] | None = None,
) -> dict[str, Any]:
    """Build a run-level summary explaining pipeline behavior across every proposal."""
    document_count_by_treatment: Counter[str] = Counter()
    for proposal in proposals:
        for treatment in proposal.knowledge_base_treatment:
            document_count_by_treatment[str(treatment.recommended_rag_treatment)] += 1

    questions_by_proposal: Counter[str] = Counter()
    questions_by_decision_type: Counter[str] = Counter()
    for question in arbitrated_questions:
        questions_by_proposal[question.proposal_id] += 1
        questions_by_decision_type[str(question.decision_type or "unknown")] += 1

    synthesis_sources: Counter[str] = Counter(p.synthesis_source for p in proposals)

    usage_records = usage_records or []
    bedrock_calls_by_stage: Counter[str] = Counter()
    tokens_by_stage: Counter[str] = Counter()
    for record in usage_records:
        stage = f"pass{record.pass_number}"
        bedrock_calls_by_stage[stage] += 1
        tokens_by_stage[stage] += record.total_tokens or 0

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "proposal_count": len(proposals),
        "document_count_by_treatment": dict(sorted(document_count_by_treatment.items())),
        "questions_total": len(arbitrated_questions),
        "questions_by_proposal": dict(sorted(questions_by_proposal.items())),
        "questions_by_decision_type": dict(sorted(questions_by_decision_type.items())),
        "questions_suppressed_count": suppressed_count,
        "questions_resolved_by_prior_override_count": resolved_by_override_count,
        "synthesis_sources": dict(sorted(synthesis_sources.items())),
        "bedrock_calls_by_stage": dict(sorted(bedrock_calls_by_stage.items())),
        "bedrock_tokens_by_stage": dict(sorted(tokens_by_stage.items())),
        "object_types_in_manifest": [
            str(ManifestObjectType.proposal_record),
            str(ManifestObjectType.document),
        ],
    }
