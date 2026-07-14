"""Tests for Phase 3 schema validation and metadata storage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from proposal_ingest.metadata_store import MetadataStore
from proposal_ingest.schemas import (
    APP_SCHEMA_VERSION,
    BedrockUsageRecord,
    DocumentMetadata,
    FolderMetadata,
    InventoryRecord,
    ReviewQuestion,
    RunManifest,
    S3ManifestRow,
    Uncertainty,
)


def make_valid_inventory_record() -> dict[str, object]:
    """Return a valid inventory row payload for schema tests."""
    return {
        "document_id": "doc_1234567890abcdef",
        "proposal_id": "prop_2025-demo__abc12345",
        "source_path": "C:/source/2025/Demo Proposal/Technical Volume.pdf",
        "relative_path": "2025/Demo Proposal/Technical Volume.pdf",
        "year_folder": "2025",
        "proposal_branch": "Demo Proposal",
        "file_name_original": "Technical Volume.pdf",
        "file_name_safe": "Technical_Volume.pdf",
        "extension": ".pdf",
        "size_bytes": 1024,
        "modified_time": "2026-05-16T12:00:00+00:00",
        "sha256": "a" * 64,
        "eligible_for_processing": True,
        "processing_strategy": "direct_bedrock",
        "processing_status": "pending_analysis",
        "skip_reason": None,
        "duplicate_of_document_id": None,
        "superseded_by_document_id": None,
    }


def make_valid_document_metadata(*, document_id: str = "doc_1234567890abcdef") -> dict[str, object]:
    """Return a valid document metadata payload with optional document ID override."""
    inventory = make_valid_inventory_record()
    inventory["document_id"] = document_id
    return {
        "schema_version": APP_SCHEMA_VERSION,
        "document_id": document_id,
        "proposal_id": "prop_2025-demo__abc12345",
        "run_id": "run_20260516_120000_ab12cd",
        "system": {
            "source_path": inventory["source_path"],
            "relative_path": inventory["relative_path"],
            "year_folder": inventory["year_folder"],
            "proposal_branch": inventory["proposal_branch"],
            "file_name_original": inventory["file_name_original"],
            "file_name_safe": inventory["file_name_safe"],
            "extension": inventory["extension"],
            "size_bytes": inventory["size_bytes"],
            "modified_time": inventory["modified_time"],
            "sha256": inventory["sha256"],
            "processing_strategy": inventory["processing_strategy"],
            "processing_status": inventory["processing_status"],
        },
        "document_identity": {
            "canonical_document_title": "Technical Volume",
            "document_category": "proposal_response",
            "document_role": "technical_volume",
            "origin_type": "generated_response",
            "version_status": "final",
            "draft_or_final_evidence": "Filename indicates final technical volume.",
            "language": "English",
            "document_date": "2025-08-15",
        },
        "proposal_context": {
            "canonical_proposal_name": "Demo Battery Proposal",
            "proposal_short_name": "Demo Battery",
            "agency": "DOE",
            "agency_subunit": "ARPA-E",
            "program": "FOA",
            "phase": "Phase I",
            "topic_number": "DEMO-001",
            "topic_title": "Battery innovation",
            "solicitation_number": "DE-FOA-0000001",
            "submission_date": "2025-08-15",
            "response_date": "2025-10-01",
            "status": "submitted",
            "award_status": "pending",
            "award_amount": None,
            "lead_organization": "Empower",
            "prime_or_sub": "prime",
            "partners": ["OSU"],
            "customer_or_sponsor": "DOE",
        },
        "content": {
            "summary_short": "A short summary.",
            "summary_detailed": "A longer structured summary.",
            "primary_topics": ["batteries"],
            "technical_keywords": ["anode"],
            "technologies": ["glass anode"],
            "applications": ["EV"],
            "performance_metrics": [
                {
                    "metric_name": "cycle life",
                    "value": "1000",
                    "unit": "cycles",
                    "condition": ">80% capacity retention",
                    "demonstrated_or_target": "target",
                    "confidence": 0.82,
                }
            ],
            "technical_claims": [
                {
                    "claim": "Fast charging improves performance.",
                    "claim_type": "performance",
                    "support_level": "document_claim",
                    "evidence_text_summary": "Stated in the approach section.",
                    "needs_verification": True,
                    "confidence": 0.78,
                }
            ],
            "risks": ["Scale-up risk"],
            "milestones": ["Build cells"],
            "deliverables": ["Technical report"],
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
            "include_reason": "Core proposal response document.",
            "exclude_reason": None,
            "recommended_chunking_strategy": "section_headings",
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
            "document_category": 0.91,
            "document_role": 0.9,
            "origin_type": 0.89,
            "version_status": 0.88,
            "canonical_proposal_name": 0.84,
            "agency": 0.93,
            "program": 0.87,
            "status": 0.8,
            "award_status": 0.6,
            "include_in_clean_set": 0.95,
            "include_in_future_rag": 0.95,
            "rag_priority": 0.9,
        },
        "questions_for_user": [],
        "fields_needing_review": [],
        "processing_notes": [],
    }


def make_valid_folder_metadata() -> dict[str, object]:
    """Return a valid folder metadata payload for storage tests."""
    return {
        "schema_version": APP_SCHEMA_VERSION,
        "proposal_id": "prop_2025-demo__abc12345",
        "year_folder": "2025",
        "proposal_branch": "Demo Proposal",
        "canonical_proposal_name": "Demo Battery Proposal",
        "proposal_short_name": "Demo Battery",
        "agency": "DOE",
        "agency_subunit": "ARPA-E",
        "program": "FOA",
        "phase": "Phase I",
        "topic_number": "DEMO-001",
        "topic_title": "Battery innovation",
        "solicitation_number": "DE-FOA-0000001",
        "submission_date": "2025-08-15",
        "selection_notification_date": None,
        "award_date": None,
        "status": "submitted",
        "award_status": "pending",
        "lead_organization": "Empower",
        "prime_or_sub": "prime",
        "partners": ["OSU"],
        "technical_focus": ["glass anode"],
        "commercial_focus": ["electric vehicles"],
        "folder_summary_short": "A concise folder summary.",
        "folder_summary_detailed": "A detailed folder summary.",
        "opportunity_context_summary": "Relevant opportunity details.",
        "generated_response_summary": "The branch contains proposal response material.",
        "key_documents": [
            {
                "document_id": "doc_1234567890abcdef",
                "file_name_original": "Technical Volume.pdf",
                "document_role": "technical_volume",
                "include_in_clean_set": True,
            }
        ],
        "included_document_count": 1,
        "excluded_document_count": 0,
        "manual_review_count": 0,
        "open_critical_questions": 0,
        "ready_for_clean_set": True,
        "ready_for_future_s3": True,
        "tracker_match_status": "not_attempted",
        "tracker_disagreements": [],
    }


def test_valid_document_metadata_passes() -> None:
    """A valid document metadata dict should deserialize without errors."""
    metadata = DocumentMetadata.model_validate(make_valid_document_metadata())

    assert metadata.document_identity.document_role == "technical_volume"
    assert metadata.confidence.document_category == pytest.approx(0.91)


def test_invalid_document_metadata_raises() -> None:
    """Missing required fields should raise a validation error."""
    invalid = make_valid_document_metadata()
    invalid["document_identity"]["document_category"] = "bogus_category"
    invalid["confidence"].pop("document_role")

    with pytest.raises(ValidationError):
        DocumentMetadata.model_validate(invalid)


def test_document_metadata_defaults_to_empty_uncertainties() -> None:
    """A clear, unambiguous document should validate with zero uncertainties."""
    metadata = DocumentMetadata.model_validate(make_valid_document_metadata())

    assert metadata.uncertainties == []


def test_document_metadata_accepts_proposal_scoped_uncertainty() -> None:
    """Proposal-wide unknowns should validate as a single proposal-scoped uncertainty."""
    payload = make_valid_document_metadata()
    payload["uncertainties"] = [
        {
            "field": "proposal_context.award_status",
            "scope": "proposal",
            "current_guess": "awarded",
            "confidence": 0.65,
            "evidence": ["Folder path contains AWD", "This file is an old technical-volume draft"],
            "missing_evidence": "Award notice or authoritative tracker result",
            "downstream_impact": "medium",
            "reason_unresolved": "The document itself does not establish the final proposal outcome",
        }
    ]

    metadata = DocumentMetadata.model_validate(payload)

    assert len(metadata.uncertainties) == 1
    uncertainty = metadata.uncertainties[0]
    assert uncertainty.scope == "proposal"
    assert uncertainty.downstream_impact == "medium"
    assert uncertainty.field == "proposal_context.award_status"


def test_uncertainty_rejects_invalid_scope_and_impact() -> None:
    """Uncertainty scope and downstream_impact must use the controlled vocabulary."""
    with pytest.raises(ValidationError):
        Uncertainty.model_validate(
            {
                "field": "document_identity.version_status",
                "scope": "bogus_scope",
                "confidence": 0.5,
                "reason_unresolved": "n/a",
            }
        )

    with pytest.raises(ValidationError):
        Uncertainty.model_validate(
            {
                "field": "document_identity.version_status",
                "downstream_impact": "extreme",
                "confidence": 0.5,
                "reason_unresolved": "n/a",
            }
        )


def test_missing_document_date_alone_does_not_require_uncertainty() -> None:
    """A null document_date by itself should validate without any uncertainty entry."""
    payload = make_valid_document_metadata()
    payload["document_identity"]["document_date"] = None

    metadata = DocumentMetadata.model_validate(payload)

    assert metadata.document_identity.document_date is None
    assert metadata.uncertainties == []


def test_legacy_document_metadata_with_questions_for_user_still_loads() -> None:
    """Metadata written before the uncertainty model existed must remain loadable."""
    payload = make_valid_document_metadata()
    assert "uncertainties" not in payload
    payload["questions_for_user"] = [
        {
            "question_id": "q_legacy_001",
            "field": "document_identity.version_status",
            "question": "Is this the final submitted version?",
            "priority": "high",
            "suggested_options": ["final", "draft", "unknown"],
            "model_guess": "unknown",
            "answer_type": "enum",
        }
    ]

    metadata = DocumentMetadata.model_validate(payload)

    assert metadata.uncertainties == []
    assert len(metadata.questions_for_user) == 1
    assert metadata.questions_for_user[0].field == "document_identity.version_status"


def test_valid_folder_metadata_passes() -> None:
    """A valid folder metadata dict should deserialize without errors."""
    metadata = FolderMetadata.model_validate(make_valid_folder_metadata())

    assert metadata.ready_for_clean_set is True
    assert metadata.key_documents[0].document_id == "doc_1234567890abcdef"


def test_inventory_record_validates_and_rejects_bad_enums() -> None:
    """Inventory rows should enforce enum validation for processing status."""
    record = InventoryRecord.model_validate(make_valid_inventory_record())
    assert record.processing_status == "pending_analysis"

    invalid = make_valid_inventory_record()
    invalid["processing_status"] = "wrong"
    with pytest.raises(ValidationError):
        InventoryRecord.model_validate(invalid)


def test_additional_models_validate() -> None:
    """Review, usage, and manifest support models should accept valid payloads."""
    question = ReviewQuestion.model_validate(
        {
            "question_id": "q_123",
            "proposal_id": "prop_2025-demo__abc12345",
            "document_id": "doc_1234567890abcdef",
            "question": "Confirm topic number",
            "priority": "medium",
            "status": "open",
        }
    )
    usage = BedrockUsageRecord.model_validate(
        {
            "run_id": "run_20260516_120000_ab12cd",
            "document_id": "doc_1234567890abcdef",
            "proposal_id": "prop_2025-demo__abc12345",
            "model_id": "anthropic.claude-opus-4-6-v1",
            "processing_strategy": "direct_bedrock",
            "pass_number": 1,
            "start_time": "2026-05-16T12:00:00+00:00",
            "end_time": "2026-05-16T12:00:05+00:00",
            "latency_seconds": 5.0,
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "success": True,
            "error_type": None,
            "error_message": None,
        }
    )
    manifest_row = S3ManifestRow.model_validate(
        {
            "document_id": "doc_1234567890abcdef",
            "proposal_id": "prop_2025-demo__abc12345",
            "local_clean_path": "C:/output/mirror/2025/demo/documents/Technical_Volume.pdf",
            "metadata_path": "C:/output/mirror/2025/demo/metadata/doc_1234567890abcdef.json",
            "recommended_s3_key": "proposal-history/2025/demo/documents/Technical_Volume.pdf",
            "include_in_future_rag": True,
            "rag_priority": "high",
        }
    )

    assert question.status == "open"
    assert usage.total_tokens == 150
    assert manifest_row.rag_priority == "high"


def test_metadata_store_writes_document_json_and_jsonl(tmp_path: Path) -> None:
    """The metadata store should persist per-document JSON and aggregate JSONL."""
    run_dir = tmp_path / "run_20260516_120000_ab12cd"
    store = MetadataStore(run_dir)
    document_one = DocumentMetadata.model_validate(make_valid_document_metadata())
    document_two = DocumentMetadata.model_validate(
        make_valid_document_metadata(document_id="doc_fedcba0987654321")
    )

    document_json_path = store.write_document_metadata(document_one)
    jsonl_path = store.write_document_metadata_jsonl([document_one, document_two])

    assert document_json_path == (
        run_dir / "document_metadata" / "by_document_id" / "doc_1234567890abcdef.json"
    )
    with document_json_path.open(encoding="utf-8") as handle:
        written_document = json.load(handle)
    assert written_document["document_id"] == "doc_1234567890abcdef"
    assert jsonl_path.exists()
    with jsonl_path.open(encoding="utf-8") as handle:
        lines = [json.loads(line) for line in handle if line.strip()]
    assert [line["document_id"] for line in lines] == [
        "doc_1234567890abcdef",
        "doc_fedcba0987654321",
    ]


def test_metadata_store_writes_folder_metadata_and_run_manifest(tmp_path: Path) -> None:
    """The metadata store should persist folder metadata and the run manifest."""
    run_dir = tmp_path / "run_20260516_120000_ab12cd"
    store = MetadataStore(run_dir)
    folder = FolderMetadata.model_validate(make_valid_folder_metadata())
    manifest = RunManifest.model_validate(
        {
            "schema_version": APP_SCHEMA_VERSION,
            "run_id": "run_20260516_120000_ab12cd",
            "command": "scan",
            "source_root": "C:/source",
            "output_root": "C:/output",
            "config_snapshot": {"mock_bedrock": False},
            "git_commit": None,
            "timestamp": "2026-05-16T12:00:00+00:00",
            "mock_bedrock": False,
        }
    )

    folder_path = store.write_folder_metadata(folder)
    manifest_path = store.write_run_manifest(manifest)

    assert folder_path == run_dir / "folder_metadata" / "prop_2025-demo__abc12345.json"
    assert manifest_path == run_dir / "run_manifest.json"
    with folder_path.open(encoding="utf-8") as handle:
        written_folder = json.load(handle)
    with manifest_path.open(encoding="utf-8") as handle:
        written_manifest = json.load(handle)
    assert written_folder["proposal_id"] == "prop_2025-demo__abc12345"
    assert written_manifest["command"] == "scan"
