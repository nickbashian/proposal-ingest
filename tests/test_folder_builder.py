"""Tests for Phase 11 folder metadata synthesis."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from proposal_ingest.folder_builder import (
    FolderBuildResult,
    _identify_key_documents,
    build_all_folders,
    build_folder_metadata,
    render_folder_summary_markdown,
)
from proposal_ingest.config import RuntimeConfig
from proposal_ingest.metadata_store import MetadataStore
from proposal_ingest.schemas import (
    APP_SCHEMA_VERSION,
    DocumentMetadata,
    FolderMetadata,
    TrackerMatchStatus,
)
from proposal_ingest.tracker import TrackerRow, load_tracker_rows

# ---------------------------------------------------------------------------
# Minimal document factory
# ---------------------------------------------------------------------------

_BASE_DOC: dict = {
    "schema_version": APP_SCHEMA_VERSION,
    "document_id": "doc_aabbccdd00000001",
    "proposal_id": "prop_2025-demo__abc12345",
    "run_id": "run_20260516_120000_ab12cd",
    "system": {
        "source_path": "C:/source/2025/Demo/file.pdf",
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
    origin_type: str = "generated_response",
    agency: str = "DOE",
    program: str = "SBIR",
    status: str = "submitted",
    award_status: str = "pending",
    canonical_proposal_name: str = "Demo Battery Proposal",
    include_in_clean_set: bool = True,
    manual_review_required: bool = False,
    rag_priority: str = "high",
    sensitivity_labels: list[str] | None = None,
    partners: list[str] | None = None,
    primary_topics: list[str] | None = None,
    technologies: list[str] | None = None,
    applications: list[str] | None = None,
    summary_short: str = "A short summary.",
    useful_context_summary: str = "",
    questions_for_user: list[dict] | None = None,
    uncertainties: list[dict] | None = None,
    submission_date: str | None = "2025-08-15",
) -> DocumentMetadata:
    payload = copy.deepcopy(_BASE_DOC)
    payload["document_id"] = document_id
    payload["proposal_id"] = proposal_id
    payload["system"]["file_name_original"] = file_name
    payload["system"]["file_name_safe"] = file_name
    payload["document_identity"]["document_role"] = role
    payload["document_identity"]["origin_type"] = origin_type
    payload["proposal_context"]["agency"] = agency
    payload["proposal_context"]["program"] = program
    payload["proposal_context"]["status"] = status
    payload["proposal_context"]["award_status"] = award_status
    payload["proposal_context"]["canonical_proposal_name"] = canonical_proposal_name
    payload["proposal_context"]["submission_date"] = submission_date
    payload["proposal_context"]["partners"] = partners or ["OSU"]
    payload["proposal_context"]["phase"] = "Phase I"
    payload["content"]["primary_topics"] = primary_topics or ["batteries"]
    payload["content"]["technologies"] = technologies or ["glass anode"]
    payload["content"]["applications"] = applications or ["EV"]
    payload["content"]["summary_short"] = summary_short
    payload["opportunity_treatment"]["useful_context_summary"] = useful_context_summary
    payload["inclusion"]["include_in_clean_set"] = include_in_clean_set
    payload["inclusion"]["include_in_future_rag"] = include_in_clean_set
    payload["inclusion"]["rag_priority"] = rag_priority
    if include_in_clean_set:
        payload["inclusion"]["include_reason"] = "Included."
        payload["inclusion"]["exclude_reason"] = None
    else:
        payload["inclusion"]["include_reason"] = None
        payload["inclusion"]["exclude_reason"] = "Excluded."
    payload["sensitivity"]["manual_review_required"] = manual_review_required
    payload["sensitivity"]["sensitivity_labels"] = sensitivity_labels or ["internal"]
    payload["questions_for_user"] = questions_for_user or []
    payload["uncertainties"] = uncertainties or []
    return DocumentMetadata.model_validate(payload)


# ---------------------------------------------------------------------------
# Count aggregation
# ---------------------------------------------------------------------------


def test_included_excluded_and_manual_review_counts() -> None:
    docs = [
        _make_doc(document_id="doc_001", include_in_clean_set=True),
        _make_doc(document_id="doc_002", include_in_clean_set=True),
        _make_doc(document_id="doc_003", include_in_clean_set=False, manual_review_required=False),
        _make_doc(document_id="doc_004", include_in_clean_set=False, manual_review_required=True),
    ]
    meta = build_folder_metadata(docs, use_mock=True)
    assert meta.included_document_count == 2
    assert meta.excluded_document_count == 1
    assert meta.manual_review_count == 1


def test_empty_documents_raises() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        build_folder_metadata([], use_mock=True)


# ---------------------------------------------------------------------------
# Consensus field aggregation
# ---------------------------------------------------------------------------


def test_consensus_agency_and_program() -> None:
    docs = [
        _make_doc(document_id="doc_001", agency="DOE", program="SBIR"),
        _make_doc(document_id="doc_002", agency="DOE", program="SBIR"),
        _make_doc(document_id="doc_003", agency="NSF", program="unknown"),
    ]
    meta = build_folder_metadata(docs, use_mock=True)
    assert str(meta.agency) == "DOE"
    assert str(meta.program) == "SBIR"


def test_consensus_enum_tie_returns_unknown() -> None:
    docs = [
        _make_doc(document_id="doc_001", agency="DOE"),
        _make_doc(document_id="doc_002", agency="NSF"),
    ]
    meta = build_folder_metadata(docs, use_mock=True)
    assert str(meta.agency) == "unknown"


def test_consensus_proposal_name_most_common_wins() -> None:
    docs = [
        _make_doc(document_id="doc_001", canonical_proposal_name="Alpha"),
        _make_doc(document_id="doc_002", canonical_proposal_name="Alpha"),
        _make_doc(document_id="doc_003", canonical_proposal_name="Beta"),
    ]
    meta = build_folder_metadata(docs, use_mock=True)
    assert meta.canonical_proposal_name == "Alpha"


def test_consensus_string_tie_returns_fallback() -> None:
    docs = [
        _make_doc(document_id="doc_001", canonical_proposal_name="Alpha"),
        _make_doc(document_id="doc_002", canonical_proposal_name="Beta"),
    ]
    meta = build_folder_metadata(docs, use_mock=True)
    assert meta.canonical_proposal_name == "Demo Battery Proposal"


def test_partners_are_union_deduped() -> None:
    docs = [
        _make_doc(document_id="doc_001", partners=["OSU", "MIT"]),
        _make_doc(document_id="doc_002", partners=["MIT", "Stanford"]),
    ]
    meta = build_folder_metadata(docs, use_mock=True)
    assert "OSU" in meta.partners
    assert "MIT" in meta.partners
    assert "Stanford" in meta.partners
    assert meta.partners.count("MIT") == 1


def test_technical_focus_union() -> None:
    docs = [
        _make_doc(document_id="doc_001", primary_topics=["batteries"], technologies=["anode"]),
        _make_doc(document_id="doc_002", primary_topics=["electrolyte"], technologies=["anode"]),
    ]
    meta = build_folder_metadata(docs, use_mock=True)
    assert "batteries" in meta.technical_focus
    assert "electrolyte" in meta.technical_focus
    assert meta.technical_focus.count("anode") == 1


# ---------------------------------------------------------------------------
# Key document selection
# ---------------------------------------------------------------------------


def test_key_documents_by_role_priority() -> None:
    docs = [
        _make_doc(document_id="doc_001", role="technical_volume"),
        _make_doc(document_id="doc_002", role="budget"),
        _make_doc(document_id="doc_003", role="abstract"),
    ]
    meta = build_folder_metadata(docs, use_mock=True)
    roles = [str(kd.document_role) for kd in meta.key_documents]
    # technical_volume precedes budget in priority list
    assert roles.index("technical_volume") < roles.index("budget")


def test_key_documents_prefer_included_over_excluded_same_role() -> None:
    included_doc = _make_doc(document_id="doc_inc", role="budget", include_in_clean_set=True)
    excluded_doc = _make_doc(document_id="doc_exc", role="budget", include_in_clean_set=False)
    result = _identify_key_documents([excluded_doc, included_doc])
    budget_kd = next((kd for kd in result if str(kd.document_role) == "budget"), None)
    assert budget_kd is not None
    assert budget_kd.document_id == "doc_inc"


def test_high_rag_priority_doc_appended_if_role_not_in_priority_list() -> None:
    docs = [
        _make_doc(document_id="doc_001", role="tracker", rag_priority="high"),
    ]
    meta = build_folder_metadata(docs, use_mock=True)
    ids = [kd.document_id for kd in meta.key_documents]
    assert "doc_001" in ids


def test_key_documents_capped_at_ten() -> None:
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
    meta = build_folder_metadata(docs, use_mock=True)
    assert len(meta.key_documents) <= 10


# ---------------------------------------------------------------------------
# Readiness flags
# ---------------------------------------------------------------------------


def test_ready_for_clean_set_true_when_included_and_no_critical_questions() -> None:
    docs = [_make_doc(document_id="doc_001", include_in_clean_set=True)]
    meta = build_folder_metadata(docs, use_mock=True)
    assert meta.ready_for_clean_set is True


def test_ready_for_clean_set_false_when_no_included_docs() -> None:
    docs = [_make_doc(document_id="doc_001", include_in_clean_set=False)]
    meta = build_folder_metadata(docs, use_mock=True)
    assert meta.ready_for_clean_set is False


def test_ready_for_clean_set_false_when_open_critical_question() -> None:
    questions = [
        {
            "question_id": "q_001",
            "field": "document_role",
            "question": "What is the role?",
            "priority": "critical",
            "status": "open",
        }
    ]
    docs = [
        _make_doc(
            document_id="doc_001",
            include_in_clean_set=True,
            questions_for_user=questions,
        )
    ]
    meta = build_folder_metadata(docs, use_mock=True)
    assert meta.ready_for_clean_set is False
    assert meta.open_critical_questions == 1


def test_ready_for_clean_set_false_when_critical_uncertainty() -> None:
    uncertainties = [
        {
            "field": "proposal_context.award_status",
            "scope": "proposal",
            "confidence": 0.5,
            "downstream_impact": "critical",
            "reason_unresolved": "Award status could not be confirmed from this document.",
        }
    ]
    docs = [
        _make_doc(
            document_id="doc_001",
            include_in_clean_set=True,
            uncertainties=uncertainties,
        )
    ]
    meta = build_folder_metadata(docs, use_mock=True)
    assert meta.ready_for_clean_set is False
    assert meta.open_critical_questions == 1


def test_ready_for_future_s3_false_when_export_control_label() -> None:
    docs = [
        _make_doc(
            document_id="doc_001",
            include_in_clean_set=True,
            manual_review_required=True,
            sensitivity_labels=["export_control_review"],
        )
    ]
    meta = build_folder_metadata(docs, use_mock=True)
    assert meta.ready_for_future_s3 is False


def test_ready_for_future_s3_false_when_export_control_without_manual_review() -> None:
    docs = [
        _make_doc(
            document_id="doc_001",
            include_in_clean_set=True,
            manual_review_required=False,
            sensitivity_labels=["export_control_review"],
        )
    ]
    meta = build_folder_metadata(docs, use_mock=True)
    assert meta.ready_for_future_s3 is False


def test_ready_for_future_s3_true_when_no_export_control() -> None:
    docs = [
        _make_doc(
            document_id="doc_001",
            include_in_clean_set=True,
            sensitivity_labels=["internal"],
        )
    ]
    meta = build_folder_metadata(docs, use_mock=True)
    assert meta.ready_for_future_s3 is True


# ---------------------------------------------------------------------------
# Mock summaries
# ---------------------------------------------------------------------------


def test_mock_summary_short_is_deterministic() -> None:
    docs = [_make_doc(document_id="doc_001")]
    meta1 = build_folder_metadata(docs, use_mock=True)
    meta2 = build_folder_metadata(docs, use_mock=True)
    assert meta1.folder_summary_short == meta2.folder_summary_short


def test_mock_summary_short_contains_expected_fields() -> None:
    docs = [_make_doc(document_id="doc_001", agency="DOE", program="SBIR", status="submitted")]
    meta = build_folder_metadata(docs, use_mock=True)
    assert "DOE" in meta.folder_summary_short
    assert "SBIR" in meta.folder_summary_short


def test_mock_opportunity_context_summary_from_docs() -> None:
    docs = [
        _make_doc(
            document_id="doc_001",
            useful_context_summary="Useful opportunity context here.",
        )
    ]
    meta = build_folder_metadata(docs, use_mock=True)
    assert "Useful opportunity context here." in meta.opportunity_context_summary


def test_mock_generated_response_summary_only_from_generated_response_docs() -> None:
    docs = [
        _make_doc(
            document_id="doc_001",
            origin_type="generated_response",
            summary_short="Our response.",
            include_in_clean_set=True,
        ),
        _make_doc(
            document_id="doc_002",
            origin_type="source_opportunity",
            summary_short="RFP text.",
            include_in_clean_set=True,
        ),
    ]
    meta = build_folder_metadata(docs, use_mock=True)
    assert "Our response." in meta.generated_response_summary
    assert "RFP text." not in meta.generated_response_summary


# ---------------------------------------------------------------------------
# Tracker integration
# ---------------------------------------------------------------------------


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


def test_tracker_match_overrides_submission_date() -> None:
    docs = [_make_doc(document_id="doc_001", submission_date="2025-08-15")]
    tracker_rows = _make_tracker_rows("Demo Battery Proposal")
    meta = build_folder_metadata(docs, tracker_rows=tracker_rows, use_mock=True)
    assert meta.submission_date == "2025-09-01"
    assert str(meta.tracker_match_status) == TrackerMatchStatus.matched.value


def test_tracker_match_sets_selection_and_award_dates() -> None:
    docs = [_make_doc(document_id="doc_001")]
    tracker_rows = _make_tracker_rows("Demo Battery Proposal")
    meta = build_folder_metadata(docs, tracker_rows=tracker_rows, use_mock=True)
    assert meta.selection_notification_date == "2025-11-01"
    assert meta.award_date == "2026-01-15"


def test_tracker_match_overrides_status() -> None:
    docs = [_make_doc(document_id="doc_001", status="submitted")]
    tracker_rows = _make_tracker_rows("Demo Battery Proposal")
    meta = build_folder_metadata(docs, tracker_rows=tracker_rows, use_mock=True)
    assert str(meta.status) == "awarded"


def test_tracker_disagreement_logged_when_submission_date_differs() -> None:
    docs = [_make_doc(document_id="doc_001", submission_date="2025-08-15")]
    tracker_rows = _make_tracker_rows("Demo Battery Proposal")
    meta = build_folder_metadata(docs, tracker_rows=tracker_rows, use_mock=True)
    disagree_fields = [d["field"] for d in meta.tracker_disagreements]
    assert "submission_date" in disagree_fields


def test_tracker_not_attempted_when_no_rows() -> None:
    docs = [_make_doc(document_id="doc_001")]
    meta = build_folder_metadata(docs, tracker_rows=None, use_mock=True)
    assert str(meta.tracker_match_status) == TrackerMatchStatus.not_attempted.value


def test_tracker_unmatched_when_name_does_not_match() -> None:
    docs = [_make_doc(document_id="doc_001", canonical_proposal_name="Completely Different")]
    tracker_rows = _make_tracker_rows("Unrelated Other Project")
    meta = build_folder_metadata(docs, tracker_rows=tracker_rows, use_mock=True)
    assert str(meta.tracker_match_status) in {
        TrackerMatchStatus.unmatched.value,
        TrackerMatchStatus.ambiguous.value,
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _make_simple_folder_metadata() -> FolderMetadata:
    docs = [_make_doc(document_id="doc_001")]
    return build_folder_metadata(docs, use_mock=True)


def test_markdown_contains_proposal_name() -> None:
    meta = _make_simple_folder_metadata()
    md = render_folder_summary_markdown(meta)
    assert meta.canonical_proposal_name in md


def test_markdown_has_document_counts_table() -> None:
    meta = _make_simple_folder_metadata()
    md = render_folder_summary_markdown(meta)
    assert "Included in clean set" in md
    assert "Excluded" in md
    assert "Manual review required" in md


def test_markdown_has_readiness_section() -> None:
    meta = _make_simple_folder_metadata()
    md = render_folder_summary_markdown(meta)
    assert "Ready for clean set" in md
    assert "Ready for future S3" in md


def test_markdown_has_tracker_section() -> None:
    meta = _make_simple_folder_metadata()
    md = render_folder_summary_markdown(meta)
    assert "## Tracker" in md
    assert "Match status" in md


def test_markdown_key_documents_section() -> None:
    docs = [
        _make_doc(document_id="doc_001", role="technical_volume"),
        _make_doc(document_id="doc_002", role="budget"),
    ]
    meta = build_folder_metadata(docs, use_mock=True)
    md = render_folder_summary_markdown(meta)
    assert "## Key Documents" in md
    assert "technical_volume" in md


def test_markdown_tracker_disagreements_listed() -> None:
    docs = [_make_doc(document_id="doc_001", submission_date="2025-08-15")]
    tracker_rows = _make_tracker_rows("Demo Battery Proposal")
    meta = build_folder_metadata(docs, tracker_rows=tracker_rows, use_mock=True)
    md = render_folder_summary_markdown(meta)
    assert "submission_date" in md


# ---------------------------------------------------------------------------
# build_all_folders (store integration)
# ---------------------------------------------------------------------------


def test_build_all_folders_groups_by_proposal_id(tmp_path: Path) -> None:
    store = MetadataStore(tmp_path / "run_001")
    doc_a1 = _make_doc(document_id="doc_a01", proposal_id="prop_aaa")
    doc_a2 = _make_doc(document_id="doc_a02", proposal_id="prop_aaa")
    doc_b1 = _make_doc(document_id="doc_b01", proposal_id="prop_bbb")
    for doc in [doc_a1, doc_a2, doc_b1]:
        store.write_document_metadata(doc, append_jsonl=False)

    results = build_all_folders(store, use_mock=True)

    assert len(results) == 2
    proposal_ids = {r.proposal_id for r in results}
    assert "prop_aaa" in proposal_ids
    assert "prop_bbb" in proposal_ids


def test_build_all_folders_writes_json_and_md(tmp_path: Path) -> None:
    store = MetadataStore(tmp_path / "run_001")
    doc = _make_doc(document_id="doc_001", proposal_id="prop_aaa")
    store.write_document_metadata(doc, append_jsonl=False)

    results = build_all_folders(store, use_mock=True)

    assert len(results) == 1
    result = results[0]
    assert isinstance(result, FolderBuildResult)
    assert result.json_path.exists()
    assert result.summary_md_path.exists()
    md_text = result.summary_md_path.read_text(encoding="utf-8")
    assert "## Summary" in md_text


def test_build_all_folders_writes_mirror_outputs(tmp_path: Path) -> None:
    store = MetadataStore(tmp_path / "run_001")
    doc = _make_doc(document_id="doc_001", proposal_id="prop_aaa")
    store.write_document_metadata(doc, append_jsonl=False)

    build_all_folders(store, use_mock=True)

    mirror_dir = store.mirror_branch_dir("2025", "Demo Battery Proposal")
    assert (mirror_dir / "folder_metadata.json").exists()
    assert (mirror_dir / "folder_summary.md").exists()


def test_build_all_folders_returns_empty_when_no_docs(tmp_path: Path) -> None:
    store = MetadataStore(tmp_path / "run_001")
    results = build_all_folders(store, use_mock=True)
    assert results == []


def test_build_all_folders_with_tracker_rows(tmp_path: Path) -> None:
    store = MetadataStore(tmp_path / "run_001")
    doc = _make_doc(
        document_id="doc_001",
        proposal_id="prop_aaa",
        submission_date="2025-08-15",
        canonical_proposal_name="Demo Battery Proposal",
    )
    store.write_document_metadata(doc, append_jsonl=False)
    tracker_rows = _make_tracker_rows("Demo Battery Proposal")

    results = build_all_folders(store, tracker_rows=tracker_rows, use_mock=True)

    assert len(results) == 1
    assert results[0].metadata.submission_date == "2025-09-01"


def test_build_all_folders_json_roundtrip(tmp_path: Path) -> None:
    store = MetadataStore(tmp_path / "run_001")
    doc = _make_doc(document_id="doc_001", proposal_id="prop_aaa")
    store.write_document_metadata(doc, append_jsonl=False)

    results = build_all_folders(store, use_mock=True)

    json_text = results[0].json_path.read_text(encoding="utf-8")
    loaded = FolderMetadata.model_validate_json(json_text)
    assert loaded.proposal_id == "prop_aaa"
    assert loaded.included_document_count == 1


# ---------------------------------------------------------------------------
# Fake fixture smoke test (uses sample_data)
# ---------------------------------------------------------------------------


def test_tracker_fixture_integration(tmp_path: Path) -> None:
    """Verify folder builder works with the real fake tracker fixture."""
    fixture = (
        Path(__file__).resolve().parents[1]
        / "sample_data"
        / "fake_source_root"
        / "General"
        / "Empower Grant Activities"
        / "Grants In Progress"
        / "fake_grants_tracker.xlsx"
    )
    if not fixture.exists():
        pytest.skip("fake_grants_tracker.xlsx not found")

    tracker_rows = load_tracker_rows(fixture)
    docs = [
        _make_doc(
            document_id="doc_001",
            canonical_proposal_name="2025 Fake DOE SBIR Battery Project",
            proposal_id="prop_fake",
            include_in_clean_set=True,
        )
    ]
    meta = build_folder_metadata(docs, tracker_rows=tracker_rows, use_mock=True)
    assert str(meta.tracker_match_status) == TrackerMatchStatus.matched.value


def test_real_summary_mode_uses_default_config_and_parses_wrapped_json(monkeypatch) -> None:
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
            "Here is the JSON you asked for:\n```json\n"
            '{"folder_summary_short":"Short","folder_summary_detailed":"Detailed",'
            '"opportunity_context_summary":"Opportunity","generated_response_summary":"Response"}'
            "\n```\nThanks.",
            {},
        )

    monkeypatch.setattr("proposal_ingest.config.load_runtime_config", _fake_load_runtime_config)
    monkeypatch.setattr(
        "proposal_ingest.bedrock_client.create_bedrock_runtime_client",
        _fake_create_client,
    )
    monkeypatch.setattr(
        "proposal_ingest.bedrock_client.call_converse_with_text",
        _fake_call,
    )

    meta = build_folder_metadata(docs, use_mock=False, config=None)

    assert captured["model_id"] == "us.anthropic.claude-opus-4-6-v1"
    assert captured["call_model_id"] == "us.anthropic.claude-opus-4-6-v1"
    assert meta.folder_summary_short == "Short"
    assert meta.folder_summary_detailed == "Detailed"
    assert meta.opportunity_context_summary == "Opportunity"
    assert meta.generated_response_summary == "Response"
