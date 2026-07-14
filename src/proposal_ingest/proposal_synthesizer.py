"""Synthesize canonical, cross-document proposal-level metadata records.

Documents remain evidence underneath a proposal; this module reconciles
document-level metadata, uncertainties, and tracker data into one
``ProposalMetadata`` record per proposal. A deterministic Python pass always
runs first (used directly in mock mode, and as the packet/fallback for a
real Bedrock synthesis call); Bedrock reasoning is optional and never
required for CI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from proposal_ingest.aggregation import (
    KEY_DOCUMENT_ROLES,
    MAX_KEY_DOCUMENTS,
    consensus_enum,
    consensus_str,
    first_non_none,
    union_lists,
)
from proposal_ingest.config import load_knowledge_base_policies
from proposal_ingest.human_overrides import (
    canonical_field_key,
    load_human_overrides,
    output_root_from_run_dir,
    reapply_overrides_to_documents,
    reapply_overrides_to_proposal,
)
from proposal_ingest.json_utils import parse_json_object_response
from proposal_ingest.logging_utils import get_logger
from proposal_ingest.metadata_store import MetadataStore
from proposal_ingest.schemas import (
    APP_SCHEMA_VERSION,
    Agency,
    AuthorityRank,
    DocumentCategory,
    DocumentLineageEntry,
    DocumentMetadata,
    DocumentRole,
    KnowledgeBaseTreatment,
    Program,
    ProposalCanonicalIdentity,
    ProposalEvidenceRef,
    ProposalKeyDocument,
    ProposalMetadata,
    ProposalOrganizations,
    ProposalStatus,
    ProposalSummary,
    RagPriority,
    RecommendedRagTreatment,
    TrackerMatchStatus,
    UncertaintyImpact,
    UncertaintyScope,
    UnresolvedDecision,
    UnresolvedDecisionType,
    VersionStatus,
)
from proposal_ingest.tracker import TrackerRow, apply_tracker_overrides_to_identity

logger = get_logger("proposal_synthesizer")

# ---------------------------------------------------------------------------
# Standing-policy role/version classification
# ---------------------------------------------------------------------------

_HIGH_VALUE_ROLES: frozenset[DocumentRole] = frozenset(
    {
        DocumentRole.technical_volume,
        DocumentRole.project_description,
        DocumentRole.statement_of_work,
        DocumentRole.award_notice,
        DocumentRole.review_feedback,
        DocumentRole.final_report,
        DocumentRole.milestone_report,
        DocumentRole.commercialization_plan,
    }
)

_LOW_VALUE_ROLES: frozenset[DocumentRole] = frozenset(
    {
        DocumentRole.rfp,
        DocumentRole.foa,
        DocumentRole.topic_description,
        DocumentRole.submission_instructions,
        DocumentRole.terms_and_conditions,
        DocumentRole.dfars_clauses,
    }
)

_AUTHORITATIVE_VERSION_STATUSES: frozenset[VersionStatus] = frozenset(
    {VersionStatus.final, VersionStatus.submitted_version}
)

_LOW_PRIORITY_VERSION_STATUSES: frozenset[VersionStatus] = frozenset(
    {VersionStatus.draft, VersionStatus.working_version}
)

_RAG_PRIORITY_TO_TREATMENT: dict[RagPriority, RecommendedRagTreatment] = {
    RagPriority.high: RecommendedRagTreatment.full_document,
    RagPriority.medium: RecommendedRagTreatment.summary_only,
    RagPriority.low: RecommendedRagTreatment.metadata_only,
    RagPriority.exclude: RecommendedRagTreatment.exclude,
}

_IMPACT_ORDER: dict[UncertaintyImpact, int] = {
    UncertaintyImpact.critical: 3,
    UncertaintyImpact.high: 2,
    UncertaintyImpact.medium: 1,
    UncertaintyImpact.low: 0,
}


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class ProposalSynthesisResult:
    """Outcome of synthesizing one proposal record."""

    proposal_id: str
    metadata: ProposalMetadata
    json_path: Path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def synthesize_proposal_metadata(
    documents: list[DocumentMetadata],
    *,
    run_id: str | None = None,
    tracker_rows: list[TrackerRow] | None = None,
    use_mock: bool = True,
    config: Any = None,
    policies: list[dict[str, str]] | None = None,
) -> ProposalMetadata:
    """Synthesize a canonical ProposalMetadata record from per-document metadata.

    All documents must share the same proposal_id. A deterministic pass
    always runs first; in mock mode (or when Bedrock fails) it is the final
    result. In real mode, its output seeds a single Bedrock call that may
    refine canonical identity, lineage, treatment, and unresolved decisions.
    """
    if not documents:
        raise ValueError("documents must be non-empty")

    deterministic = build_deterministic_proposal_metadata(
        documents, run_id=run_id, tracker_rows=tracker_rows
    )
    if use_mock:
        return deterministic

    resolved_policies = (
        policies
        if policies is not None
        else load_knowledge_base_policies(config.synthesis.policies_path if config else None)
    )
    try:
        return _call_bedrock_for_proposal_synthesis(
            documents,
            deterministic=deterministic,
            tracker_rows=tracker_rows,
            policies=resolved_policies,
            config=config,
        )
    except Exception:
        logger.exception(
            "Bedrock proposal synthesis failed for %s; falling back to deterministic synthesis",
            deterministic.proposal_id,
        )
        fallback = deterministic.model_copy(deep=True)
        fallback.synthesis_source = "deterministic_fallback"
        return fallback


def synthesize_all_proposals(
    store: MetadataStore,
    *,
    tracker_rows: list[TrackerRow] | None = None,
    use_mock: bool = True,
    config: Any = None,
    policies: list[dict[str, str]] | None = None,
) -> list[ProposalSynthesisResult]:
    """Load all document metadata from store, group by proposal_id, synthesize.

    Durable human overrides from prior runs (``output_root/review/human_overrides.jsonl``)
    are replayed onto the loaded documents before synthesis and onto the final
    proposal record after synthesis, so a resynthesis on a fresh document set
    never silently discards a previously applied human answer.
    """
    docs_by_proposal: dict[str, list[DocumentMetadata]] = {}
    for doc in store.load_document_metadata_by_id().values():
        docs_by_proposal.setdefault(doc.proposal_id, []).append(doc)

    resolved_policies = (
        policies
        if policies is not None
        else load_knowledge_base_policies(config.synthesis.policies_path if config else None)
    )
    overrides = load_human_overrides(output_root_from_run_dir(store.run_dir))

    results: list[ProposalSynthesisResult] = []
    all_docs: list[DocumentMetadata] = []
    for proposal_id in sorted(docs_by_proposal):
        docs = docs_by_proposal[proposal_id]
        proposal_overrides = [o for o in overrides if o.proposal_id == proposal_id]
        if proposal_overrides:
            docs = reapply_overrides_to_documents(docs, proposal_overrides)
            for doc in docs:
                store.write_document_metadata(doc, append_jsonl=False)
        all_docs.extend(docs)
        logger.info("Synthesizing proposal metadata for %s (%d docs)", proposal_id, len(docs))
        try:
            metadata = synthesize_proposal_metadata(
                docs,
                run_id=docs[0].run_id,
                tracker_rows=tracker_rows,
                use_mock=use_mock,
                config=config,
                policies=resolved_policies,
            )
        except Exception:
            logger.exception("Failed to synthesize proposal metadata for %s", proposal_id)
            continue

        if proposal_overrides:
            metadata = reapply_overrides_to_proposal(metadata, proposal_overrides)

        json_path = store.write_proposal_metadata(metadata)
        results.append(
            ProposalSynthesisResult(proposal_id=proposal_id, metadata=metadata, json_path=json_path)
        )

    if overrides:
        store.write_document_metadata_jsonl(sorted(all_docs, key=lambda doc: doc.document_id))
    store.write_proposal_metadata_jsonl([result.metadata for result in results])
    return results


def build_deterministic_proposal_metadata(
    documents: list[DocumentMetadata],
    *,
    run_id: str | None = None,
    tracker_rows: list[TrackerRow] | None = None,
) -> ProposalMetadata:
    """Build a ProposalMetadata record using only deterministic Python logic.

    This is the mock-mode result and the Bedrock-failure fallback; it never
    calls Bedrock and is safe to run in CI.
    """
    if not documents:
        raise ValueError("documents must be non-empty")

    first = documents[0]
    (
        canonical_identity,
        organizations,
        tracker_match_status,
        tracker_disagreements,
        matched_tracker_row,
    ) = _build_canonical_identity(documents, tracker_rows)

    document_lineage = _build_document_lineage(documents)
    lineage_by_id = {entry.document_id: entry for entry in document_lineage}
    key_documents = _select_key_documents(documents, lineage_by_id)
    knowledge_base_treatment = _build_knowledge_base_treatment(documents, lineage_by_id)
    evidence = _build_evidence(documents, tracker_match_status, matched_tracker_row)
    unresolved_decisions = _consolidate_unresolved_decisions(
        documents, tracker_match_status=tracker_match_status
    )
    proposal_summary = _build_deterministic_proposal_summary(
        documents,
        canonical_identity=canonical_identity,
        document_lineage=document_lineage,
    )

    return ProposalMetadata(
        proposal_id=first.proposal_id,
        year_folder=first.system.year_folder,
        proposal_branch=first.system.proposal_branch,
        run_id=run_id,
        canonical_identity=canonical_identity,
        organizations=organizations,
        proposal_summary=proposal_summary,
        document_lineage=document_lineage,
        key_documents=key_documents,
        knowledge_base_treatment=knowledge_base_treatment,
        evidence=evidence,
        unresolved_decisions=unresolved_decisions,
        tracker_match_status=tracker_match_status,
        tracker_disagreements=tracker_disagreements,
        synthesis_source="mock",
        document_count=len(documents),
    )


# ---------------------------------------------------------------------------
# Canonical identity + tracker reconciliation
# ---------------------------------------------------------------------------


def _build_canonical_identity(
    documents: list[DocumentMetadata],
    tracker_rows: list[TrackerRow] | None,
) -> tuple[
    ProposalCanonicalIdentity,
    ProposalOrganizations,
    TrackerMatchStatus,
    list[dict[str, Any]],
    TrackerRow | None,
]:
    proposal_branch = documents[0].system.proposal_branch

    proposal_name = consensus_str(
        [d.proposal_context.canonical_proposal_name for d in documents],
        fallback=proposal_branch,
        ignore={"unknown", ""},
    )
    agency = consensus_enum(
        [str(d.proposal_context.agency) for d in documents],
        default=Agency.unknown.value,
        ignore={Agency.unknown.value},
    )
    program = consensus_enum(
        [str(d.proposal_context.program) for d in documents],
        default=Program.unknown.value,
        ignore={Program.unknown.value},
    )
    status_str = consensus_enum(
        [str(d.proposal_context.status) for d in documents],
        default=ProposalStatus.unknown.value,
        ignore={ProposalStatus.unknown.value},
    )
    award_status = consensus_str(
        [d.proposal_context.award_status for d in documents],
        fallback="unknown",
        ignore={"unknown", ""},
    )
    submission_date = first_non_none([d.proposal_context.submission_date for d in documents])
    phase = first_non_none([d.proposal_context.phase for d in documents])
    topic_number = first_non_none([d.proposal_context.topic_number for d in documents])
    topic_title = first_non_none([d.proposal_context.topic_title for d in documents])
    solicitation_number = first_non_none(
        [d.proposal_context.solicitation_number for d in documents]
    )
    lead_organization = first_non_none([d.proposal_context.lead_organization for d in documents])
    prime_or_sub = consensus_str(
        [d.proposal_context.prime_or_sub for d in documents],
        fallback="unknown",
        ignore={"unknown", ""},
    )
    partners = union_lists([d.proposal_context.partners for d in documents])
    award_amount = next(
        (
            d.proposal_context.award_amount
            for d in documents
            if d.proposal_context.award_amount is not None
        ),
        None,
    )
    customer_or_sponsor = first_non_none(
        [d.proposal_context.customer_or_sponsor for d in documents]
    )

    tracker_override = apply_tracker_overrides_to_identity(
        proposal_branch=proposal_branch,
        tracker_rows=tracker_rows,
        canonical_proposal_name=proposal_name,
        submission_date=submission_date,
        status=status_str,
        award_status=award_status,
    )
    proposal_name = tracker_override.canonical_proposal_name
    submission_date = tracker_override.submission_date
    selection_notification_date = tracker_override.selection_notification_date
    award_date = tracker_override.award_date
    status_str = tracker_override.status
    award_status = tracker_override.award_status
    tracker_match_status = tracker_override.match_status
    tracker_disagreements = tracker_override.disagreements
    matched_tracker_row = tracker_override.matched_row

    canonical_identity = ProposalCanonicalIdentity(
        proposal_name=proposal_name,
        agency=agency,  # type: ignore[arg-type]
        program=program,  # type: ignore[arg-type]
        phase=phase,
        topic_number=topic_number,
        topic_title=topic_title,
        solicitation_number=solicitation_number,
        submission_date=submission_date,
        selection_notification_date=selection_notification_date,
        award_date=award_date,
        status=status_str,  # type: ignore[arg-type]
        award_status=award_status,
        award_amount=award_amount,
    )
    organizations = ProposalOrganizations(
        lead_organization=lead_organization,
        prime_or_sub=prime_or_sub,
        partners=partners,
        customer_or_sponsor=customer_or_sponsor,
    )
    return (
        canonical_identity,
        organizations,
        tracker_match_status,
        tracker_disagreements,
        matched_tracker_row,
    )


# ---------------------------------------------------------------------------
# Document lineage and authority ranking
# ---------------------------------------------------------------------------


def _authority_rank_for(doc: DocumentMetadata) -> AuthorityRank:
    version = doc.document_identity.version_status
    if version == VersionStatus.superseded:
        return AuthorityRank.superseded
    if version in _AUTHORITATIVE_VERSION_STATUSES:
        return AuthorityRank.authoritative
    if not doc.inclusion.include_in_clean_set and not doc.inclusion.include_in_future_rag:
        return AuthorityRank.excluded
    return AuthorityRank.supporting


def _build_document_lineage(documents: list[DocumentMetadata]) -> list[DocumentLineageEntry]:
    by_role: dict[DocumentRole, list[DocumentMetadata]] = {}
    for doc in documents:
        by_role.setdefault(doc.document_identity.document_role, []).append(doc)

    entries: list[DocumentLineageEntry] = []
    for doc in documents:
        role = doc.document_identity.document_role
        version = doc.document_identity.version_status
        rank = _authority_rank_for(doc)
        is_authoritative = rank == AuthorityRank.authoritative

        authoritative_siblings = [
            sibling
            for sibling in by_role.get(role, [])
            if sibling.document_id != doc.document_id
            and _authority_rank_for(sibling) == AuthorityRank.authoritative
        ]

        superseded_by: str | None = None
        contains_unique_reasoning = False
        rationale = ""
        if rank != AuthorityRank.authoritative and authoritative_siblings:
            superseded_by = authoritative_siblings[0].document_id
            own_detail = doc.content.summary_detailed.strip()
            if own_detail and not any(
                own_detail == sibling.content.summary_detailed.strip()
                for sibling in authoritative_siblings
            ):
                contains_unique_reasoning = True
                rationale = (
                    "This document's detailed summary is not reflected in the authoritative "
                    f"{role} ({superseded_by})."
                )

        if not rationale:
            rationale = (
                f"Version status '{version}' treated as authoritative for role '{role}'."
                if is_authoritative
                else f"Version status '{version}' is not authoritative for role '{role}'."
            )

        entries.append(
            DocumentLineageEntry(
                document_id=doc.document_id,
                file_name_original=doc.system.file_name_original,
                document_role=role,
                version_status=version,
                authority_rank=rank,
                is_authoritative=is_authoritative,
                superseded_by_document_id=superseded_by,
                contains_unique_reasoning=contains_unique_reasoning,
                rationale=rationale,
            )
        )
    return entries


# ---------------------------------------------------------------------------
# Key document selection
# ---------------------------------------------------------------------------


def _select_key_documents(
    documents: list[DocumentMetadata],
    lineage_by_id: dict[str, DocumentLineageEntry],
) -> list[ProposalKeyDocument]:
    docs_by_role: dict[DocumentRole, DocumentMetadata] = {}
    for doc in documents:
        role = doc.document_identity.document_role
        current = docs_by_role.get(role)
        if current is None:
            docs_by_role[role] = doc
            continue
        if (
            lineage_by_id[doc.document_id].is_authoritative
            and not lineage_by_id[current.document_id].is_authoritative
        ):
            docs_by_role[role] = doc

    seen_ids: set[str] = set()
    result: list[ProposalKeyDocument] = []

    for role in KEY_DOCUMENT_ROLES:
        if len(result) >= MAX_KEY_DOCUMENTS:
            break
        role_doc = docs_by_role.get(role)
        if role_doc and role_doc.document_id not in seen_ids:
            seen_ids.add(role_doc.document_id)
            result.append(
                ProposalKeyDocument(
                    document_id=role_doc.document_id,
                    file_name_original=role_doc.system.file_name_original,
                    document_role=role,
                    reason=f"Highest-priority available document for role '{role}'.",
                )
            )

    for doc in documents:
        if len(result) >= MAX_KEY_DOCUMENTS:
            break
        if doc.inclusion.rag_priority == RagPriority.high and doc.document_id not in seen_ids:
            seen_ids.add(doc.document_id)
            result.append(
                ProposalKeyDocument(
                    document_id=doc.document_id,
                    file_name_original=doc.system.file_name_original,
                    document_role=doc.document_identity.document_role,
                    reason="Document-level rag_priority is high.",
                )
            )

    return result


# ---------------------------------------------------------------------------
# Knowledge-base treatment
# ---------------------------------------------------------------------------


def _policy_label_for(
    doc: DocumentMetadata, lineage: DocumentLineageEntry
) -> tuple[str | None, str | None]:
    """Return (policy_applied, exception_reason) for one document's treatment."""
    role = doc.document_identity.document_role
    category = doc.document_identity.document_category

    if lineage.authority_rank == AuthorityRank.superseded:
        if lineage.contains_unique_reasoning:
            return (
                "superseded_low_priority",
                "Retained despite supersession: contains unique reasoning not present "
                "in the authoritative version.",
            )
        return "superseded_low_priority", None

    if (
        lineage.authority_rank == AuthorityRank.supporting
        and doc.document_identity.version_status in _LOW_PRIORITY_VERSION_STATUSES
    ):
        if lineage.contains_unique_reasoning:
            return (
                "draft_retained_for_unique_reasoning",
                "Retained at low priority: contains unique reasoning not present "
                "in the authoritative version.",
            )
        return "draft_retained_for_unique_reasoning", None

    if role in _HIGH_VALUE_ROLES:
        return "high_value_roles", None

    if role in _LOW_VALUE_ROLES:
        if doc.opportunity_treatment.opportunity_context_useful:
            return (
                "evaluation_criteria_may_be_useful",
                "Opportunity context flagged useful despite being a normally low-value role.",
            )
        return "opportunity_boilerplate_not_high_value", None

    if category == DocumentCategory.budget_financial or doc.sensitivity.contains_budget_or_rates:
        return "budgets_excluded_from_rag", None

    if doc.sensitivity.contains_personal_info:
        return "budgets_excluded_from_rag", None

    return None, None


def _recommended_treatment_for(doc: DocumentMetadata) -> RecommendedRagTreatment:
    # The budgets/PII-excluded-from-RAG policy always wins: a high rag_priority
    # (e.g. a mis-classified document) must never surface budget/PII text.
    if doc.sensitivity.contains_budget_or_rates or doc.sensitivity.contains_personal_info:
        return RecommendedRagTreatment.exclude
    if (
        doc.opportunity_treatment.opportunity_context_useful
        or doc.opportunity_treatment.boilerplate_heavy
    ):
        return doc.opportunity_treatment.recommended_rag_treatment
    return _RAG_PRIORITY_TO_TREATMENT.get(
        doc.inclusion.rag_priority, RecommendedRagTreatment.metadata_only
    )


def _build_knowledge_base_treatment(
    documents: list[DocumentMetadata],
    lineage_by_id: dict[str, DocumentLineageEntry],
) -> list[KnowledgeBaseTreatment]:
    treatment: list[KnowledgeBaseTreatment] = []
    for doc in documents:
        lineage = lineage_by_id[doc.document_id]
        policy_applied, exception_reason = _policy_label_for(doc, lineage)
        treatment.append(
            KnowledgeBaseTreatment(
                document_id=doc.document_id,
                recommended_rag_treatment=_recommended_treatment_for(doc),
                rag_priority=doc.inclusion.rag_priority,
                policy_applied=policy_applied,
                exception_reason=exception_reason,
            )
        )
    return treatment


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def _build_evidence(
    documents: list[DocumentMetadata],
    tracker_match_status: TrackerMatchStatus,
    matched_tracker_row: TrackerRow | None,
) -> list[ProposalEvidenceRef]:
    evidence: list[ProposalEvidenceRef] = []
    if tracker_match_status == TrackerMatchStatus.matched and matched_tracker_row is not None:
        evidence.append(
            ProposalEvidenceRef(
                source="tracker",
                document_id=None,
                claim=f"Grants tracker row {matched_tracker_row.row_id} matched this proposal branch.",
                confidence=0.9,
            )
        )

    best_identity_doc = max(
        documents,
        key=lambda d: float(d.confidence.canonical_proposal_name),
        default=None,
    )
    if best_identity_doc is not None:
        evidence.append(
            ProposalEvidenceRef(
                source="document",
                document_id=best_identity_doc.document_id,
                claim=(
                    "Highest-confidence document-derived canonical proposal name: "
                    f"'{best_identity_doc.proposal_context.canonical_proposal_name}'."
                ),
                confidence=float(best_identity_doc.confidence.canonical_proposal_name),
            )
        )
    return evidence


# ---------------------------------------------------------------------------
# Unresolved-decision consolidation
# ---------------------------------------------------------------------------


def _consolidate_unresolved_decisions(
    documents: list[DocumentMetadata],
    *,
    tracker_match_status: TrackerMatchStatus,
) -> list[UnresolvedDecision]:
    """Group candidate decisions by canonical field key, not by raw field string.

    Document-level uncertainties are namespaced under ``proposal_context.*``
    while the tracker-conflict fallback below reports under
    ``canonical_identity.*``; both can legitimately describe the same
    underlying issue (for example ``award_status``). Grouping by canonical
    key here keeps this merge consistent with
    ``question_arbiter.stable_proposal_question_id``, which also collapses
    on the canonical key — otherwise the two code paths could mint the same
    question ID for two different ``UnresolvedDecision`` entries, silently
    double-counting one issue against the per-proposal question budget.
    """
    grouped: dict[str, dict[str, Any]] = {}

    def _merge(
        *,
        field: str,
        current_guess: str | None,
        confidence: float,
        evidence: list[str],
        affected_document_ids: list[str],
        downstream_impact: UncertaintyImpact,
        reason: str,
    ) -> None:
        key = canonical_field_key(field)
        bucket = grouped.setdefault(
            key,
            {
                "field": field,
                "current_guess": current_guess,
                "confidence": confidence,
                "evidence": [],
                "affected_document_ids": [],
                "downstream_impact": downstream_impact,
                "reasons": [],
            },
        )
        bucket["affected_document_ids"].extend(affected_document_ids)
        if confidence > bucket["confidence"]:
            bucket["confidence"] = confidence
            bucket["current_guess"] = current_guess
        for item in evidence:
            if item not in bucket["evidence"]:
                bucket["evidence"].append(item)
        if _IMPACT_ORDER[downstream_impact] > _IMPACT_ORDER[bucket["downstream_impact"]]:
            bucket["downstream_impact"] = downstream_impact
        if reason not in bucket["reasons"]:
            bucket["reasons"].append(reason)

    for doc in documents:
        for uncertainty in doc.uncertainties:
            if uncertainty.scope not in (
                UncertaintyScope.proposal,
                UncertaintyScope.document_family,
            ):
                continue
            _merge(
                field=uncertainty.field,
                current_guess=uncertainty.current_guess,
                confidence=float(uncertainty.confidence),
                evidence=list(uncertainty.evidence),
                affected_document_ids=[doc.document_id],
                downstream_impact=uncertainty.downstream_impact,
                reason=uncertainty.reason_unresolved,
            )

    if tracker_match_status != TrackerMatchStatus.matched:
        for fallback_decision in _detect_conflicting_award_status(documents):
            _merge(
                field=fallback_decision.field,
                current_guess=fallback_decision.current_guess,
                confidence=float(fallback_decision.confidence),
                evidence=(
                    [fallback_decision.evidence_summary]
                    if fallback_decision.evidence_summary
                    else []
                ),
                affected_document_ids=list(fallback_decision.affected_document_ids),
                downstream_impact=fallback_decision.downstream_impact,
                reason=fallback_decision.reason_unresolved,
            )

    return [
        UnresolvedDecision(
            field=bucket["field"],
            scope=UncertaintyScope.proposal,
            decision_type=UnresolvedDecisionType.proposal_fact,
            current_guess=bucket["current_guess"],
            confidence=bucket["confidence"],
            evidence_summary="; ".join(bucket["evidence"]) if bucket["evidence"] else "",
            affected_document_ids=sorted(set(bucket["affected_document_ids"])),
            downstream_impact=bucket["downstream_impact"],
            reason_unresolved=" ".join(bucket["reasons"]),
        )
        for _key, bucket in sorted(grouped.items())
    ]


def _detect_conflicting_award_status(documents: list[DocumentMetadata]) -> list[UnresolvedDecision]:
    values = {
        d.proposal_context.award_status
        for d in documents
        if d.proposal_context.award_status not in {"", "unknown"}
    }
    if len(values) <= 1:
        return []
    return [
        UnresolvedDecision(
            field="canonical_identity.award_status",
            scope=UncertaintyScope.proposal,
            decision_type=UnresolvedDecisionType.proposal_fact,
            current_guess=None,
            confidence=0.0,
            evidence_summary=(
                "Documents disagree on award_status without a matching tracker row: "
                + ", ".join(sorted(values))
            ),
            affected_document_ids=sorted(
                d.document_id for d in documents if d.proposal_context.award_status in values
            ),
            downstream_impact=UncertaintyImpact.high,
            reason_unresolved=(
                "No tracker match is available to arbitrate conflicting award-status "
                "evidence across documents."
            ),
        )
    ]


# ---------------------------------------------------------------------------
# Proposal-summary narrative (deterministic)
# ---------------------------------------------------------------------------


def _build_deterministic_proposal_summary(
    documents: list[DocumentMetadata],
    *,
    canonical_identity: ProposalCanonicalIdentity,
    document_lineage: list[DocumentLineageEntry],
) -> ProposalSummary:
    authoritative_ids = {entry.document_id for entry in document_lineage if entry.is_authoritative}
    authoritative_docs = [d for d in documents if d.document_id in authoritative_ids] or [
        d for d in documents if d.inclusion.include_in_clean_set
    ]

    technical_objective = next(
        (
            d.content.summary_short.strip()
            for d in authoritative_docs
            if d.content.summary_short.strip()
        ),
        "",
    )
    proposed_approach = next(
        (
            d.content.summary_detailed.strip()
            for d in authoritative_docs
            if d.content.summary_detailed.strip()
        ),
        "",
    )
    target_applications = union_lists([d.content.applications for d in documents])
    key_performance_targets = union_lists(
        [[metric.metric_name for metric in d.content.performance_metrics] for d in documents]
    )
    commercial_strategy = next(
        (
            d.content.summary_short.strip()
            for d in documents
            if d.document_identity.document_role == DocumentRole.commercialization_plan
            and d.content.summary_short.strip()
        ),
        "",
    )
    reviewer_feedback = [
        d.content.summary_short.strip()
        for d in documents
        if d.document_identity.document_role == DocumentRole.review_feedback
        and d.content.summary_short.strip()
    ]
    outcome = f"{canonical_identity.status} ({canonical_identity.award_status})"

    return ProposalSummary(
        technical_objective=technical_objective,
        proposed_approach=proposed_approach,
        target_applications=target_applications,
        key_performance_targets=key_performance_targets,
        commercial_strategy=commercial_strategy,
        reviewer_feedback=reviewer_feedback,
        outcome=outcome,
    )


# ---------------------------------------------------------------------------
# Context packet construction (for real Bedrock synthesis)
# ---------------------------------------------------------------------------


def _document_value_priority(doc: DocumentMetadata) -> tuple[int, int]:
    role = doc.document_identity.document_role
    version = doc.document_identity.version_status
    role_score = 0 if role in _HIGH_VALUE_ROLES else (2 if role in _LOW_VALUE_ROLES else 1)
    version_score = 0 if version in _AUTHORITATIVE_VERSION_STATUSES else 1
    return (role_score, version_score)


def _select_full_text(
    documents: list[DocumentMetadata],
    *,
    max_documents: int,
    max_chars_per_doc: int,
) -> dict[str, str]:
    """Select a bounded set of documents to include full/extracted text for.

    Low-value roles (long opportunity/legal boilerplate) never receive full
    text, regardless of budget. Documents flagged as containing budget/rate
    or personal information never receive full text either, matching the
    budgets/PII-excluded-from-RAG standing policy — only their existing,
    already-reviewed summary is exposed to the synthesis prompt. Everything
    else falls back to the document's own summary when extraction is
    unavailable or fails.
    """
    from proposal_ingest.extractors import extract_text

    ranked = sorted(documents, key=_document_value_priority)
    selected: dict[str, str] = {}
    for doc in ranked:
        if len(selected) >= max_documents:
            break
        if _document_value_priority(doc)[0] == 2:
            continue
        if doc.sensitivity.contains_budget_or_rates or doc.sensitivity.contains_personal_info:
            continue

        text = ""
        try:
            source_path = Path(doc.system.source_path)
            if source_path.exists():
                text = extract_text(source_path).strip()
        except Exception:
            logger.debug(
                "Full-text extraction failed for %s; falling back to summary", doc.document_id
            )
        if not text:
            text = doc.content.summary_detailed.strip() or doc.content.summary_short.strip()
        if text:
            selected[doc.document_id] = text[:max_chars_per_doc]
    return selected


def build_proposal_context_packet(
    documents: list[DocumentMetadata],
    *,
    tracker_rows: list[TrackerRow] | None,
    policies: list[dict[str, str]],
    preliminary: ProposalMetadata,
    max_full_text_documents: int = 8,
    max_full_text_chars_per_doc: int = 6_000,
) -> dict[str, Any]:
    """Assemble the rich per-proposal context packet used by Bedrock synthesis."""
    full_text_by_id = _select_full_text(
        documents,
        max_documents=max_full_text_documents,
        max_chars_per_doc=max_full_text_chars_per_doc,
    )

    doc_entries: list[dict[str, Any]] = []
    for doc in documents:
        doc_entries.append(
            {
                "document_id": doc.document_id,
                "file_name_original": doc.system.file_name_original,
                "document_role": str(doc.document_identity.document_role),
                "document_category": str(doc.document_identity.document_category),
                "version_status": str(doc.document_identity.version_status),
                "origin_type": str(doc.document_identity.origin_type),
                "document_date": doc.document_identity.document_date,
                "confidence": {
                    "document_role": doc.confidence.document_role,
                    "version_status": doc.confidence.version_status,
                },
                "summary_short": doc.content.summary_short,
                "summary_detailed": doc.content.summary_detailed,
                "primary_topics": doc.content.primary_topics,
                "technologies": doc.content.technologies,
                "applications": doc.content.applications,
                "performance_metrics": [
                    metric.model_dump(mode="json") for metric in doc.content.performance_metrics
                ],
                "technical_claims": [
                    claim.model_dump(mode="json") for claim in doc.content.technical_claims
                ],
                "milestones": doc.content.milestones,
                "deliverables": doc.content.deliverables,
                "partners": doc.proposal_context.partners,
                "uncertainties": [u.model_dump(mode="json") for u in doc.uncertainties],
                "inclusion": doc.inclusion.model_dump(mode="json"),
                "sensitivity": doc.sensitivity.model_dump(mode="json"),
                "opportunity_treatment": doc.opportunity_treatment.model_dump(mode="json"),
                "full_text_included": doc.document_id in full_text_by_id,
                "extracted_text_excerpt": full_text_by_id.get(doc.document_id),
            }
        )

    tracker_candidates = (
        [{"row_id": row.row_id, "values": row.values} for row in tracker_rows[:20]]
        if tracker_rows
        else []
    )

    return {
        "proposal_branch_note": (
            "Folder/branch name is low-trust context and may be imperfect; prefer "
            "document- and tracker-derived evidence over the branch name."
        ),
        "year_folder": documents[0].system.year_folder,
        "proposal_branch": documents[0].system.proposal_branch,
        "documents": doc_entries,
        "tracker_candidates": tracker_candidates,
        "standing_policies": policies,
        "preliminary_deterministic_synthesis": preliminary.model_dump(mode="json"),
    }


# ---------------------------------------------------------------------------
# Bedrock synthesis call
# ---------------------------------------------------------------------------


def _call_bedrock_for_proposal_synthesis(
    documents: list[DocumentMetadata],
    *,
    deterministic: ProposalMetadata,
    tracker_rows: list[TrackerRow] | None,
    policies: list[dict[str, str]],
    config: Any,
) -> ProposalMetadata:
    """Call Bedrock once per proposal to refine the deterministic synthesis."""
    from proposal_ingest.bedrock_client import (
        call_converse_with_text,
        create_bedrock_runtime_client,
    )
    from proposal_ingest.config import load_runtime_config
    from proposal_ingest.prompts import (
        load_proposal_synthesis_system_prompt,
        render_proposal_synthesis_user_prompt,
    )

    runtime_config = config or load_runtime_config()
    packet = build_proposal_context_packet(
        documents,
        tracker_rows=tracker_rows,
        policies=policies,
        preliminary=deterministic,
        max_full_text_documents=runtime_config.synthesis.max_full_text_documents,
        max_full_text_chars_per_doc=runtime_config.synthesis.max_full_text_chars_per_doc,
    )
    prompt = render_proposal_synthesis_user_prompt(json.dumps(packet, indent=2, sort_keys=True))

    model_id = runtime_config.bedrock.model_id
    client = create_bedrock_runtime_client(runtime_config)
    raw_text, _usage = call_converse_with_text(
        client,
        model_id=model_id,
        system_prompt=load_proposal_synthesis_system_prompt(),
        user_prompt=prompt,
        max_tokens=runtime_config.bedrock.max_tokens,
        temperature=runtime_config.bedrock.temperature,
    )
    parsed = parse_json_object_response(raw_text)

    # System-owned fields are never taken from the model: identity/location
    # come from the pipeline, and tracker matching stays Python-deterministic.
    parsed["schema_version"] = APP_SCHEMA_VERSION
    parsed["proposal_id"] = deterministic.proposal_id
    parsed["year_folder"] = deterministic.year_folder
    parsed["proposal_branch"] = deterministic.proposal_branch
    parsed["run_id"] = deterministic.run_id
    parsed["evidence"] = [e.model_dump(mode="json") for e in deterministic.evidence]
    parsed["tracker_match_status"] = deterministic.tracker_match_status
    parsed["tracker_disagreements"] = deterministic.tracker_disagreements
    parsed["document_count"] = deterministic.document_count
    parsed["synthesis_source"] = "bedrock"
    return ProposalMetadata.model_validate(parsed)
