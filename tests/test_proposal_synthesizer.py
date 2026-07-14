"""Tests for proposal-level metadata synthesis (issue #7)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from proposal_ingest.config import RuntimeConfig
from proposal_ingest.human_overrides import append_human_override
from proposal_ingest.metadata_store import MetadataStore
from proposal_ingest.proposal_synthesizer import (
    ProposalSynthesisResult,
    build_deterministic_proposal_metadata,
    build_proposal_context_packet,
    synthesize_all_proposals,
    synthesize_proposal_metadata,
)
from proposal_ingest.schemas import (
    APP_SCHEMA_VERSION,
    AuthorityRank,
    DocumentMetadata,
    HumanOverrideRecord,
    ProposalMetadata,
    TrackerMatchStatus,
    UncertaintyImpact,
)
from proposal_ingest.tracker import TrackerRow

_POLICIES = [{"id": "test_policy", "statement": "A test standing policy."}]

# ---------------------------------------------------------------------------
# Minimal document factory (mirrors tests/test_folder_builder.py)
# ---------------------------------------------------------------------------

_BASE_DOC: dict = {
    "schema_version": APP_SCHEMA_VERSION,
    "document_id": "doc_aabbccdd00000001",
    "proposal_id": "prop_2025-demo__abc12345",
    "run_id": "run_20260516_120000_ab12cd",
    "system": {
        "source_path": "/nonexistent/2025/Demo/file.pdf",
        "relative_path": "2025/Demo/file.pdf",
        "year_folder": "2025",
        "proposal_branch": "Demo Battery Proposal",
        "file_name_original": "Technical_Volume.pdf",
        "file_name_safe": "Technical_Volume.pdf",
        "extension": ".pdf",
        "size_bytes": 1024,
        "modified_time": "2026-05-16T12:00:00+00:00",
        "sha256": "a" * 64,
        "processing_strategy": "direct_bedrock",
        "processing_status": "processed_pass1",
    },
    "document_identity": {
        "canonical_document_title": "Technical Volume",
        "document_category": "proposal_response",
        "document_role": "technical_volume",
        "origin_type": "generated_response",
        "version_status": "final",
        "draft_or_final_evidence": "",
        "language": "English",
        "document_date": None,
    },
    "proposal_context": {
        "canonical_proposal_name": "Demo Battery Proposal",
        "proposal_short_name": None,
        "agency": "DOE",
        "agency_subunit": None,
        "program": "SBIR",
        "phase": "Phase I",
        "topic_number": "DEMO-001",
        "topic_title": "Battery Tech",
        "solicitation_number": "DE-FOA-0000001",
        "submission_date": "2025-08-15",
        "response_date": None,
        "status": "submitted",
        "award_status": "pending",
        "award_amount": None,
        "lead_organization": "Empower",
        "prime_or_sub": "prime",
        "partners": ["OSU"],
        "customer_or_sponsor": None,
    },
    "content": {
        "summary_short": "A short summary of the technical volume.",
        "summary_detailed": "",
        "primary_topics": ["batteries", "anodes"],
        "technical_keywords": [],
        "technologies": ["glass anode"],
        "applications": ["EV"],
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
        "recommended_rag_treatment": "full_document",
    },
    "inclusion": {
        "include_in_clean_set": True,
        "include_in_future_rag": True,
        "rag_priority": "high",
        "include_reason": "Core document.",
        "exclude_reason": None,
        "recommended_chunking_strategy": None,
    },
    "sensitivity": {
        "sensitivity_labels": ["internal"],
        "contains_budget_or_rates": False,
        "contains_personal_info": False,
        "contains_partner_confidential": False,
        "contains_export_control_flags": False,
        "manual_review_required": False,
        "manual_review_reasons": [],
    },
    "tracker_matching": {
        "tracker_match_status": "not_attempted",
        "tracker_row_id": None,
        "tracker_match_confidence": 0.0,
        "tracker_disagreements": [],
    },
    "confidence": {
        "document_category": 0.9,
        "document_role": 0.9,
        "origin_type": 0.85,
        "version_status": 0.8,
        "canonical_proposal_name": 0.85,
        "agency": 0.9,
        "program": 0.85,
        "status": 0.8,
        "award_status": 0.6,
        "include_in_clean_set": 0.9,
        "include_in_future_rag": 0.9,
        "rag_priority": 0.85,
    },
    "uncertainties": [],
    "questions_for_user": [],
    "fields_needing_review": [],
    "processing_notes": [],
}


def _make_doc(
    *,
    document_id: str = "doc_aabbccdd00000001",
    proposal_id: str = "prop_2025-demo__abc12345",
    file_name: str = "Technical_Volume.pdf",
    role: str = "technical_volume",
    version_status: str = "final",
    canonical_proposal_name: str = "Demo Battery Proposal",
    agency: str = "DOE",
    program: str = "SBIR",
    status: str = "submitted",
    award_status: str = "pending",
    submission_date: str | None = "2025-08-15",
    canonical_proposal_name_confidence: float = 0.85,
    rag_priority: str = "high",
    include_in_clean_set: bool = True,
    include_in_future_rag: bool = True,
    contains_budget_or_rates: bool = False,
    contains_personal_info: bool = False,
    opportunity_context_useful: bool = False,
    summary_short: str = "A short summary.",
    summary_detailed: str = "",
    applications: list[str] | None = None,
    uncertainties: list[dict] | None = None,
) -> DocumentMetadata:
    payload = copy.deepcopy(_BASE_DOC)
    payload["document_id"] = document_id
    payload["proposal_id"] = proposal_id
    payload["system"]["file_name_original"] = file_name
    payload["system"]["file_name_safe"] = file_name
    payload["document_identity"]["document_role"] = role
    payload["document_identity"]["version_status"] = version_status
    payload["proposal_context"]["canonical_proposal_name"] = canonical_proposal_name
    payload["proposal_context"]["agency"] = agency
    payload["proposal_context"]["program"] = program
    payload["proposal_context"]["status"] = status
    payload["proposal_context"]["award_status"] = award_status
    payload["proposal_context"]["submission_date"] = submission_date
    payload["confidence"]["canonical_proposal_name"] = canonical_proposal_name_confidence
    payload["inclusion"]["rag_priority"] = rag_priority
    payload["inclusion"]["include_in_clean_set"] = include_in_clean_set
    payload["inclusion"]["include_in_future_rag"] = include_in_future_rag
    if not include_in_clean_set and not include_in_future_rag:
        payload["inclusion"]["include_reason"] = None
        payload["inclusion"]["exclude_reason"] = "Excluded."
    payload["sensitivity"]["contains_budget_or_rates"] = contains_budget_or_rates
    payload["sensitivity"]["contains_personal_info"] = contains_personal_info
    payload["opportunity_treatment"]["opportunity_context_useful"] = opportunity_context_useful
    payload["content"]["summary_short"] = summary_short
    payload["content"]["summary_detailed"] = summary_detailed
    payload["content"]["applications"] = applications or ["EV"]
    payload["uncertainties"] = uncertainties or []
    return DocumentMetadata.model_validate(payload)


def _make_tracker_rows(proposal_name: str) -> list[TrackerRow]:
    return [
        TrackerRow(
            row_id="trk_abc123",
            values={
                "proposal_name": proposal_name,
                "submission_date": "2025-09-01",
                "selection_notification_date": "2025-11-01",
                "award_date": "2026-01-15",
                "status": "awarded",
                "award_status": "Phase I award",
            },
        )
    ]


# ---------------------------------------------------------------------------
# Basic validation
# ---------------------------------------------------------------------------


def test_empty_documents_raises() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        build_deterministic_proposal_metadata([])


def test_deterministic_synthesis_source_is_mock() -> None:
    docs = [_make_doc()]
    metadata = build_deterministic_proposal_metadata(docs)
    assert metadata.synthesis_source == "mock"
    assert metadata.document_count == 1


# ---------------------------------------------------------------------------
# Canonical identity consensus
# ---------------------------------------------------------------------------


def test_canonical_identity_consensus_agency_and_program() -> None:
    docs = [
        _make_doc(document_id="doc_001", agency="DOE", program="SBIR"),
        _make_doc(document_id="doc_002", agency="DOE", program="SBIR"),
        _make_doc(document_id="doc_003", agency="NSF", program="unknown"),
    ]
    metadata = build_deterministic_proposal_metadata(docs)
    assert str(metadata.canonical_identity.agency) == "DOE"
    assert str(metadata.canonical_identity.program) == "SBIR"


def test_canonical_identity_partners_union() -> None:
    docs = [_make_doc(document_id="doc_001")]
    metadata = build_deterministic_proposal_metadata(docs)
    assert "OSU" in metadata.organizations.partners


# ---------------------------------------------------------------------------
# Document lineage / authority ranking
# ---------------------------------------------------------------------------


def test_final_document_is_authoritative() -> None:
    docs = [_make_doc(document_id="doc_001", version_status="final")]
    metadata = build_deterministic_proposal_metadata(docs)
    entry = metadata.document_lineage[0]
    assert entry.is_authoritative is True
    assert entry.authority_rank == AuthorityRank.authoritative


def test_lone_draft_is_supporting_not_authoritative() -> None:
    docs = [_make_doc(document_id="doc_001", version_status="draft")]
    metadata = build_deterministic_proposal_metadata(docs)
    entry = metadata.document_lineage[0]
    assert entry.is_authoritative is False
    assert entry.authority_rank == AuthorityRank.supporting


def test_superseded_points_to_authoritative_sibling() -> None:
    docs = [
        _make_doc(document_id="doc_final", version_status="final"),
        _make_doc(document_id="doc_old", version_status="superseded"),
    ]
    metadata = build_deterministic_proposal_metadata(docs)
    entries = {e.document_id: e for e in metadata.document_lineage}
    assert entries["doc_old"].authority_rank == AuthorityRank.superseded
    assert entries["doc_old"].superseded_by_document_id == "doc_final"
    assert entries["doc_final"].is_authoritative is True


def test_draft_with_unique_detail_flagged_as_unique_reasoning() -> None:
    docs = [
        _make_doc(document_id="doc_final", version_status="final", summary_detailed="Final plan."),
        _make_doc(
            document_id="doc_draft",
            version_status="draft",
            summary_detailed="Earlier internal risk analysis not carried into the final.",
        ),
    ]
    metadata = build_deterministic_proposal_metadata(docs)
    entries = {e.document_id: e for e in metadata.document_lineage}
    assert entries["doc_draft"].contains_unique_reasoning is True


def test_draft_matching_final_detail_not_flagged_unique() -> None:
    docs = [
        _make_doc(document_id="doc_final", version_status="final", summary_detailed="Same text."),
        _make_doc(document_id="doc_draft", version_status="draft", summary_detailed="Same text."),
    ]
    metadata = build_deterministic_proposal_metadata(docs)
    entries = {e.document_id: e for e in metadata.document_lineage}
    assert entries["doc_draft"].contains_unique_reasoning is False


# ---------------------------------------------------------------------------
# Key documents
# ---------------------------------------------------------------------------


def test_key_documents_prefer_authoritative_over_draft_same_role() -> None:
    # rag_priority=medium on the draft isolates the role-priority selection
    # from the separate "any remaining high-priority doc" fallback pass.
    docs = [
        _make_doc(
            document_id="doc_draft",
            role="technical_volume",
            version_status="draft",
            rag_priority="medium",
        ),
        _make_doc(document_id="doc_final", role="technical_volume", version_status="final"),
    ]
    metadata = build_deterministic_proposal_metadata(docs)
    tv_key_docs = [
        kd for kd in metadata.key_documents if str(kd.document_role) == "technical_volume"
    ]
    assert len(tv_key_docs) == 1
    assert tv_key_docs[0].document_id == "doc_final"


def test_key_documents_capped() -> None:
    roles = [
        "technical_volume",
        "budget",
        "abstract",
        "rfp",
        "foa",
        "award_notice",
        "quad_chart",
        "final_report",
        "milestone_report",
        "statement_of_work",
        "commercialization_plan",
    ]
    docs = [_make_doc(document_id=f"doc_{i:03}", role=r) for i, r in enumerate(roles)]
    metadata = build_deterministic_proposal_metadata(docs)
    assert len(metadata.key_documents) <= 10


# ---------------------------------------------------------------------------
# Knowledge-base treatment
# ---------------------------------------------------------------------------


def test_high_value_role_gets_high_value_policy() -> None:
    docs = [_make_doc(document_id="doc_001", role="technical_volume", version_status="final")]
    metadata = build_deterministic_proposal_metadata(docs)
    treatment = metadata.knowledge_base_treatment[0]
    assert treatment.policy_applied == "high_value_roles"


def test_low_value_role_gets_boilerplate_policy() -> None:
    docs = [_make_doc(document_id="doc_001", role="rfp", version_status="final")]
    metadata = build_deterministic_proposal_metadata(docs)
    treatment = metadata.knowledge_base_treatment[0]
    assert treatment.policy_applied == "opportunity_boilerplate_not_high_value"


def test_low_value_role_with_useful_context_gets_exception_policy() -> None:
    docs = [
        _make_doc(
            document_id="doc_001",
            role="rfp",
            version_status="final",
            opportunity_context_useful=True,
        )
    ]
    metadata = build_deterministic_proposal_metadata(docs)
    treatment = metadata.knowledge_base_treatment[0]
    assert treatment.policy_applied == "evaluation_criteria_may_be_useful"
    assert treatment.exception_reason is not None


def test_budget_document_gets_budget_policy() -> None:
    docs = [
        _make_doc(
            document_id="doc_001",
            role="budget",
            version_status="final",
            contains_budget_or_rates=True,
        )
    ]
    metadata = build_deterministic_proposal_metadata(docs)
    treatment = metadata.knowledge_base_treatment[0]
    assert treatment.policy_applied == "budgets_excluded_from_rag"


def test_budget_flagged_document_treatment_is_excluded_even_with_high_priority() -> None:
    docs = [
        _make_doc(
            document_id="doc_001",
            role="budget",
            version_status="final",
            contains_budget_or_rates=True,
            rag_priority="high",
        )
    ]
    metadata = build_deterministic_proposal_metadata(docs)
    treatment = metadata.knowledge_base_treatment[0]
    assert str(treatment.recommended_rag_treatment) == "exclude"


def test_personal_info_flagged_document_treatment_is_excluded() -> None:
    docs = [
        _make_doc(
            document_id="doc_001",
            role="technical_volume",
            version_status="final",
            contains_personal_info=True,
            rag_priority="high",
        )
    ]
    metadata = build_deterministic_proposal_metadata(docs)
    treatment = metadata.knowledge_base_treatment[0]
    assert str(treatment.recommended_rag_treatment) == "exclude"


def test_draft_retained_policy_without_unique_reasoning() -> None:
    docs = [
        _make_doc(document_id="doc_final", role="technical_volume", version_status="final"),
        _make_doc(
            document_id="doc_draft",
            role="technical_volume",
            version_status="draft",
            summary_detailed="",
        ),
    ]
    metadata = build_deterministic_proposal_metadata(docs)
    treatment_by_id = {t.document_id: t for t in metadata.knowledge_base_treatment}
    assert treatment_by_id["doc_draft"].policy_applied == "draft_retained_for_unique_reasoning"
    assert treatment_by_id["doc_draft"].exception_reason is None


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def test_evidence_includes_tracker_when_matched() -> None:
    docs = [_make_doc(document_id="doc_001")]
    tracker_rows = _make_tracker_rows("Demo Battery Proposal")
    metadata = build_deterministic_proposal_metadata(docs, tracker_rows=tracker_rows)
    sources = [e.source for e in metadata.evidence]
    assert "tracker" in sources


def test_evidence_document_source_present_without_tracker() -> None:
    docs = [_make_doc(document_id="doc_001")]
    metadata = build_deterministic_proposal_metadata(docs)
    sources = [e.source for e in metadata.evidence]
    assert "document" in sources
    assert "tracker" not in sources


# ---------------------------------------------------------------------------
# Unresolved decision consolidation
# ---------------------------------------------------------------------------


def _proposal_uncertainty(field: str = "proposal_context.award_status") -> dict:
    return {
        "field": field,
        "scope": "proposal",
        "current_guess": "awarded",
        "confidence": 0.6,
        "evidence": ["Tracker folder path suggests an award."],
        "downstream_impact": "high",
        "reason_unresolved": "No award notice was found in this document family.",
    }


def test_duplicate_proposal_uncertainties_are_consolidated() -> None:
    docs = [
        _make_doc(document_id="doc_001", uncertainties=[_proposal_uncertainty()]),
        _make_doc(document_id="doc_002", uncertainties=[_proposal_uncertainty()]),
    ]
    metadata = build_deterministic_proposal_metadata(docs, tracker_rows=None)
    matching = [
        d for d in metadata.unresolved_decisions if d.field == "proposal_context.award_status"
    ]
    assert len(matching) == 1
    assert set(matching[0].affected_document_ids) == {"doc_001", "doc_002"}


def test_document_scope_uncertainty_not_consolidated_into_unresolved_decisions() -> None:
    doc_scoped = dict(_proposal_uncertainty())
    doc_scoped["scope"] = "document"
    docs = [_make_doc(document_id="doc_001", uncertainties=[doc_scoped])]
    metadata = build_deterministic_proposal_metadata(docs)
    assert metadata.unresolved_decisions == []


def test_conflicting_award_status_without_tracker_flagged() -> None:
    docs = [
        _make_doc(document_id="doc_001", award_status="awarded"),
        _make_doc(document_id="doc_002", award_status="rejected"),
    ]
    metadata = build_deterministic_proposal_metadata(docs, tracker_rows=None)
    matching = [
        d for d in metadata.unresolved_decisions if d.field == "canonical_identity.award_status"
    ]
    assert len(matching) == 1
    assert matching[0].downstream_impact == UncertaintyImpact.high


def test_conflicting_award_status_suppressed_when_tracker_matched() -> None:
    docs = [
        _make_doc(document_id="doc_001", award_status="awarded"),
        _make_doc(document_id="doc_002", award_status="rejected"),
    ]
    tracker_rows = _make_tracker_rows("Demo Battery Proposal")
    metadata = build_deterministic_proposal_metadata(docs, tracker_rows=tracker_rows)
    matching = [
        d for d in metadata.unresolved_decisions if d.field == "canonical_identity.award_status"
    ]
    assert matching == []


# ---------------------------------------------------------------------------
# Tracker override
# ---------------------------------------------------------------------------


def test_tracker_override_updates_canonical_identity() -> None:
    docs = [_make_doc(document_id="doc_001", submission_date="2025-08-15", status="submitted")]
    tracker_rows = _make_tracker_rows("Demo Battery Proposal")
    metadata = build_deterministic_proposal_metadata(docs, tracker_rows=tracker_rows)
    assert metadata.canonical_identity.submission_date == "2025-09-01"
    assert str(metadata.canonical_identity.status) == "awarded"
    assert metadata.tracker_match_status == TrackerMatchStatus.matched


def test_tracker_disagreement_logged() -> None:
    docs = [_make_doc(document_id="doc_001", submission_date="2025-08-15")]
    tracker_rows = _make_tracker_rows("Demo Battery Proposal")
    metadata = build_deterministic_proposal_metadata(docs, tracker_rows=tracker_rows)
    fields = [d["field"] for d in metadata.tracker_disagreements]
    assert "submission_date" in fields


def test_tracker_not_attempted_without_rows() -> None:
    docs = [_make_doc(document_id="doc_001")]
    metadata = build_deterministic_proposal_metadata(docs, tracker_rows=None)
    assert metadata.tracker_match_status == TrackerMatchStatus.not_attempted


# ---------------------------------------------------------------------------
# Context packet + full-text selection
# ---------------------------------------------------------------------------


def test_context_packet_includes_policies_and_all_documents() -> None:
    docs = [
        _make_doc(document_id="doc_001", role="technical_volume"),
        _make_doc(document_id="doc_002", role="rfp"),
    ]
    preliminary = build_deterministic_proposal_metadata(docs)
    packet = build_proposal_context_packet(
        docs, tracker_rows=None, policies=_POLICIES, preliminary=preliminary
    )
    assert packet["standing_policies"] == _POLICIES
    assert {d["document_id"] for d in packet["documents"]} == {"doc_001", "doc_002"}


def test_context_packet_low_value_role_never_gets_full_text() -> None:
    docs = [_make_doc(document_id="doc_001", role="rfp", version_status="final")]
    preliminary = build_deterministic_proposal_metadata(docs)
    packet = build_proposal_context_packet(
        docs,
        tracker_rows=None,
        policies=_POLICIES,
        preliminary=preliminary,
        max_full_text_documents=8,
    )
    assert packet["documents"][0]["full_text_included"] is False


def test_context_packet_budget_flagged_document_never_gets_full_text() -> None:
    docs = [
        _make_doc(
            document_id="doc_001",
            role="technical_volume",
            version_status="final",
            contains_budget_or_rates=True,
        )
    ]
    preliminary = build_deterministic_proposal_metadata(docs)
    packet = build_proposal_context_packet(
        docs,
        tracker_rows=None,
        policies=_POLICIES,
        preliminary=preliminary,
        max_full_text_documents=8,
    )
    assert packet["documents"][0]["full_text_included"] is False


def test_context_packet_personal_info_flagged_document_never_gets_full_text() -> None:
    docs = [
        _make_doc(
            document_id="doc_001",
            role="technical_volume",
            version_status="final",
            contains_personal_info=True,
        )
    ]
    preliminary = build_deterministic_proposal_metadata(docs)
    packet = build_proposal_context_packet(
        docs,
        tracker_rows=None,
        policies=_POLICIES,
        preliminary=preliminary,
        max_full_text_documents=8,
    )
    assert packet["documents"][0]["full_text_included"] is False


def test_context_packet_high_value_role_falls_back_to_summary_when_file_missing() -> None:
    docs = [
        _make_doc(
            document_id="doc_001",
            role="technical_volume",
            version_status="final",
            summary_detailed="Fallback detail text.",
        )
    ]
    preliminary = build_deterministic_proposal_metadata(docs)
    packet = build_proposal_context_packet(
        docs,
        tracker_rows=None,
        policies=_POLICIES,
        preliminary=preliminary,
        max_full_text_documents=8,
    )
    entry = packet["documents"][0]
    assert entry["full_text_included"] is True
    assert entry["extracted_text_excerpt"] == "Fallback detail text."


# ---------------------------------------------------------------------------
# synthesize_proposal_metadata: mock / real / fallback
# ---------------------------------------------------------------------------


def test_synthesize_mock_mode_matches_deterministic() -> None:
    docs = [_make_doc(document_id="doc_001")]
    mock_result = synthesize_proposal_metadata(docs, use_mock=True)
    deterministic = build_deterministic_proposal_metadata(docs)
    assert mock_result.canonical_identity == deterministic.canonical_identity
    assert mock_result.synthesis_source == "mock"


def test_synthesize_real_mode_resolves_policies_from_configured_path(monkeypatch) -> None:
    docs = [_make_doc(document_id="doc_001")]
    captured: dict[str, object] = {}

    def _fake_load_policies(path=None):
        captured["path"] = path
        return _POLICIES

    def _fake_load_runtime_config() -> RuntimeConfig:
        return RuntimeConfig()

    def _fake_create_client(config: RuntimeConfig) -> object:
        return object()

    def _fake_call(*_args, **kwargs):
        return ('{"canonical_identity": {"proposal_name": "unknown"}}', {})

    monkeypatch.setattr(
        "proposal_ingest.proposal_synthesizer.load_knowledge_base_policies",
        _fake_load_policies,
    )
    monkeypatch.setattr("proposal_ingest.config.load_runtime_config", _fake_load_runtime_config)
    monkeypatch.setattr(
        "proposal_ingest.bedrock_client.create_bedrock_runtime_client", _fake_create_client
    )
    monkeypatch.setattr("proposal_ingest.bedrock_client.call_converse_with_text", _fake_call)

    config = RuntimeConfig()
    config.synthesis.policies_path = "/custom/knowledge_base_policies.yaml"

    synthesize_proposal_metadata(docs, use_mock=False, config=config)

    assert captured["path"] == "/custom/knowledge_base_policies.yaml"


def test_synthesize_real_mode_calls_bedrock_and_merges_system_fields(monkeypatch) -> None:
    docs = [_make_doc(document_id="doc_001")]
    captured: dict[str, object] = {}

    def _fake_load_runtime_config() -> RuntimeConfig:
        return RuntimeConfig()

    def _fake_create_client(config: RuntimeConfig) -> object:
        captured["model_id"] = config.bedrock.model_id
        return object()

    def _fake_call(*_args, **kwargs):
        captured["call_model_id"] = kwargs["model_id"]
        return (
            '{"canonical_identity": {"proposal_name": "Bedrock Name", "status": "awarded", '
            '"award_status": "awarded"}, "organizations": {}, "proposal_summary": '
            '{"technical_objective": "Bedrock objective."}, "document_lineage": [], '
            '"key_documents": [], "knowledge_base_treatment": [], "unresolved_decisions": []}',
            {},
        )

    monkeypatch.setattr("proposal_ingest.config.load_runtime_config", _fake_load_runtime_config)
    monkeypatch.setattr(
        "proposal_ingest.bedrock_client.create_bedrock_runtime_client", _fake_create_client
    )
    monkeypatch.setattr("proposal_ingest.bedrock_client.call_converse_with_text", _fake_call)

    metadata = synthesize_proposal_metadata(docs, use_mock=False, policies=_POLICIES)

    assert captured["model_id"] == "us.anthropic.claude-opus-4-6-v1"
    assert metadata.synthesis_source == "bedrock"
    assert metadata.canonical_identity.proposal_name == "Bedrock Name"
    assert metadata.proposal_summary.technical_objective == "Bedrock objective."
    # System-owned fields are never taken from the model output.
    assert metadata.proposal_id == docs[0].proposal_id
    assert metadata.year_folder == docs[0].system.year_folder


def test_synthesize_real_mode_ignores_adversarial_system_field_overrides(monkeypatch) -> None:
    """A model response that actively tries to overwrite system-owned fields must lose."""
    docs = [_make_doc(document_id="doc_001", proposal_id="prop_2025-demo__abc12345")]

    def _fake_load_runtime_config() -> RuntimeConfig:
        return RuntimeConfig()

    def _fake_create_client(config: RuntimeConfig) -> object:
        return object()

    def _fake_call(*_args, **kwargs):
        return (
            '{"schema_version": "9.9.9", "proposal_id": "prop_attacker_injected", '
            '"year_folder": "1999", "proposal_branch": "Injected Branch", '
            '"run_id": "run_attacker_injected", "document_count": 999, '
            '"tracker_match_status": "matched", '
            '"tracker_disagreements": [{"field": "injected", "source": "attacker"}], '
            '"evidence": [{"source": "attacker", "claim": "fabricated", "confidence": 1.0}], '
            '"synthesis_source": "attacker_controlled", '
            '"canonical_identity": {"proposal_name": "Bedrock Name"}, "organizations": {}, '
            '"proposal_summary": {}, "document_lineage": [], "key_documents": [], '
            '"knowledge_base_treatment": [], "unresolved_decisions": []}',
            {},
        )

    monkeypatch.setattr("proposal_ingest.config.load_runtime_config", _fake_load_runtime_config)
    monkeypatch.setattr(
        "proposal_ingest.bedrock_client.create_bedrock_runtime_client", _fake_create_client
    )
    monkeypatch.setattr("proposal_ingest.bedrock_client.call_converse_with_text", _fake_call)

    deterministic = build_deterministic_proposal_metadata(docs)
    metadata = synthesize_proposal_metadata(docs, use_mock=False, policies=_POLICIES)

    assert metadata.schema_version == APP_SCHEMA_VERSION
    assert metadata.proposal_id == deterministic.proposal_id
    assert metadata.year_folder == deterministic.year_folder
    assert metadata.proposal_branch == deterministic.proposal_branch
    assert metadata.run_id == deterministic.run_id
    assert metadata.document_count == deterministic.document_count
    assert metadata.tracker_match_status == deterministic.tracker_match_status
    assert metadata.tracker_disagreements == deterministic.tracker_disagreements
    assert metadata.evidence == deterministic.evidence
    assert metadata.synthesis_source == "bedrock"
    # Non-system fields are still taken from the (well-formed) model response.
    assert metadata.canonical_identity.proposal_name == "Bedrock Name"


def test_synthesize_real_mode_falls_back_to_deterministic_on_bedrock_error(monkeypatch) -> None:
    docs = [_make_doc(document_id="doc_001")]

    def _fake_load_runtime_config() -> RuntimeConfig:
        return RuntimeConfig()

    def _raise_client(config: RuntimeConfig) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr("proposal_ingest.config.load_runtime_config", _fake_load_runtime_config)
    monkeypatch.setattr(
        "proposal_ingest.bedrock_client.create_bedrock_runtime_client", _raise_client
    )

    metadata = synthesize_proposal_metadata(docs, use_mock=False, policies=_POLICIES)

    assert metadata.synthesis_source == "deterministic_fallback"
    assert metadata.canonical_identity.proposal_name == "Demo Battery Proposal"


# ---------------------------------------------------------------------------
# synthesize_all_proposals (store integration)
# ---------------------------------------------------------------------------


def test_synthesize_all_proposals_groups_by_proposal_id(tmp_path: Path) -> None:
    store = MetadataStore(tmp_path / "run_001")
    doc_a1 = _make_doc(document_id="doc_a01", proposal_id="prop_aaa")
    doc_a2 = _make_doc(document_id="doc_a02", proposal_id="prop_aaa")
    doc_b1 = _make_doc(document_id="doc_b01", proposal_id="prop_bbb")
    for doc in [doc_a1, doc_a2, doc_b1]:
        store.write_document_metadata(doc, append_jsonl=False)

    results = synthesize_all_proposals(store, use_mock=True, policies=_POLICIES)

    assert len(results) == 2
    proposal_ids = {r.proposal_id for r in results}
    assert proposal_ids == {"prop_aaa", "prop_bbb"}
    for result in results:
        assert isinstance(result, ProposalSynthesisResult)
        assert result.json_path.exists()


def test_synthesize_all_proposals_returns_empty_when_no_docs(tmp_path: Path) -> None:
    store = MetadataStore(tmp_path / "run_001")
    results = synthesize_all_proposals(store, use_mock=True, policies=_POLICIES)
    assert results == []


def test_synthesize_all_proposals_writes_loadable_json(tmp_path: Path) -> None:
    store = MetadataStore(tmp_path / "run_001")
    doc = _make_doc(document_id="doc_001", proposal_id="prop_aaa")
    store.write_document_metadata(doc, append_jsonl=False)

    synthesize_all_proposals(store, use_mock=True, policies=_POLICIES)
    loaded = store.load_proposal_metadata_by_id()

    assert "prop_aaa" in loaded
    assert isinstance(loaded["prop_aaa"], ProposalMetadata)
    assert loaded["prop_aaa"].document_count == 1


def test_synthesize_all_proposals_rerun_does_not_duplicate_jsonl(tmp_path: Path) -> None:
    store = MetadataStore(tmp_path / "run_001")
    doc_a = _make_doc(document_id="doc_a", proposal_id="prop_aaa")
    doc_b = _make_doc(document_id="doc_b", proposal_id="prop_bbb")
    store.write_document_metadata(doc_a, append_jsonl=False)
    store.write_document_metadata(doc_b, append_jsonl=False)

    synthesize_all_proposals(store, use_mock=True, policies=_POLICIES)
    synthesize_all_proposals(store, use_mock=True, policies=_POLICIES)

    lines = store.all_proposal_metadata_jsonl.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_synthesize_all_proposals_replays_human_override_across_rerun(tmp_path: Path) -> None:
    """A durable human override must survive a resynthesis even against unchanged evidence.

    Two documents conflict on award_status with no tracker match, so
    deterministic synthesis alone would leave canonical_identity.award_status
    at its consensus fallback. A human override recorded in a prior run must
    win on rerun instead of being silently discarded.
    """
    run_dir = tmp_path / "logs" / "run_001"
    store = MetadataStore(run_dir)
    doc_a = _make_doc(document_id="doc_a", proposal_id="prop_aaa", award_status="awarded")
    doc_b = _make_doc(document_id="doc_b", proposal_id="prop_aaa", award_status="rejected")
    store.write_document_metadata(doc_a, append_jsonl=False)
    store.write_document_metadata(doc_b, append_jsonl=False)

    append_human_override(
        tmp_path,
        HumanOverrideRecord(
            question_id="q_test_override",
            scope="proposal",
            proposal_id="prop_aaa",
            field="canonical_identity.award_status",
            decision_type="proposal_fact",
            affected_document_ids=["doc_a", "doc_b"],
            previous_value=None,
            applied_value="awarded",
            timestamp="2026-07-14T00:00:00+00:00",
            source="human_review",
        ),
    )

    results = synthesize_all_proposals(store, use_mock=True, policies=_POLICIES)

    assert len(results) == 1
    assert results[0].metadata.canonical_identity.award_status == "awarded"


def test_synthesize_all_proposals_persists_reapplied_document_overrides(tmp_path: Path) -> None:
    """Reapplied document-level overrides must be written to disk, not just held in memory.

    Downstream stages (build-folders, build-clean-set) load document
    metadata straight from the store, so a resynthesis that only patches
    documents in memory would silently discard the override for them.
    """
    run_dir = tmp_path / "logs" / "run_001"
    store = MetadataStore(run_dir)
    doc_a = _make_doc(document_id="doc_a", proposal_id="prop_aaa", award_status="awarded")
    doc_b = _make_doc(document_id="doc_b", proposal_id="prop_aaa", award_status="rejected")
    store.write_document_metadata(doc_a, append_jsonl=False)
    store.write_document_metadata(doc_b, append_jsonl=False)

    append_human_override(
        tmp_path,
        HumanOverrideRecord(
            question_id="q_test_override",
            scope="proposal",
            proposal_id="prop_aaa",
            field="canonical_identity.award_status",
            decision_type="proposal_fact",
            affected_document_ids=["doc_a", "doc_b"],
            previous_value=None,
            applied_value="awarded",
            timestamp="2026-07-14T00:00:00+00:00",
            source="human_review",
        ),
    )

    synthesize_all_proposals(store, use_mock=True, policies=_POLICIES)

    reloaded = store.load_document_metadata_by_id()
    assert reloaded["doc_a"].proposal_context.award_status == "awarded"
    assert reloaded["doc_b"].proposal_context.award_status == "awarded"
    jsonl_lines = store.all_document_metadata_jsonl.read_text(encoding="utf-8").splitlines()
    assert len(jsonl_lines) == 2
    assert all('"award_status": "awarded"' in line for line in jsonl_lines)


def test_synthesize_all_proposals_resolves_policies_from_configured_path(
    tmp_path: Path, monkeypatch
) -> None:
    store = MetadataStore(tmp_path / "run_001")
    doc = _make_doc(document_id="doc_001", proposal_id="prop_aaa")
    store.write_document_metadata(doc, append_jsonl=False)

    captured: dict[str, object] = {}

    def _fake_load_policies(path=None):
        captured["path"] = path
        return _POLICIES

    monkeypatch.setattr(
        "proposal_ingest.proposal_synthesizer.load_knowledge_base_policies",
        _fake_load_policies,
    )

    config = RuntimeConfig()
    config.synthesis.policies_path = "/custom/knowledge_base_policies.yaml"

    synthesize_all_proposals(store, use_mock=True, config=config)

    assert captured["path"] == "/custom/knowledge_base_policies.yaml"
