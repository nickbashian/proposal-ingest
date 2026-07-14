"""Tests for Phase 9 two-pass contextual review."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from proposal_ingest.config import load_runtime_config
from proposal_ingest.metadata_store import MetadataStore
from proposal_ingest.mock_bedrock import analyze_document_mock
from proposal_ingest.schemas import (
    DocumentCategory,
    DocumentRole,
    OriginType,
    ProcessingStatus,
    Uncertainty,
)
from proposal_ingest.two_pass import (
    _merge_pass2_candidate,
    build_branch_context_packet,
    run_two_pass_review,
)


def _write_metadata_run(run_dir: Path) -> tuple[Path, str, str]:
    run_dir.mkdir(parents=True, exist_ok=True)
    store = MetadataStore(run_dir)
    run_id = run_dir.name

    tech_record = {
        "document_id": "doc_tech123456789abc",
        "proposal_id": "prop_2025-branch__abcd1234",
        "source_path": str(run_dir / "Technical Volume FINAL.docx"),
        "relative_path": "2025/Branch/Technical Volume FINAL.docx",
        "year_folder": "2025",
        "proposal_branch": "2025 Fake DOE SBIR Battery Project",
        "file_name_original": "Technical Volume FINAL.docx",
        "file_name_safe": "Technical_Volume_FINAL.docx",
        "extension": ".docx",
        "size_bytes": 100,
        "modified_time": "2026-05-17T12:00:00+00:00",
        "sha256": "1" * 64,
        "eligible_for_processing": True,
        "processing_strategy": "direct_bedrock",
        "processing_status": "pending_analysis",
    }
    letter_record = {
        "document_id": "doc_letter12345678",
        "proposal_id": "prop_2025-branch__abcd1234",
        "source_path": str(run_dir / "Support Letter.docx"),
        "relative_path": "2025/Branch/Support Letter.docx",
        "year_folder": "2025",
        "proposal_branch": "2025 Fake DOE SBIR Battery Project",
        "file_name_original": "Support Letter.docx",
        "file_name_safe": "Support_Letter.docx",
        "extension": ".docx",
        "size_bytes": 100,
        "modified_time": "2026-05-17T12:00:00+00:00",
        "sha256": "2" * 64,
        "eligible_for_processing": True,
        "processing_strategy": "direct_bedrock",
        "processing_status": "pending_analysis",
    }

    tech_path = Path(tech_record["source_path"])
    letter_path = Path(letter_record["source_path"])
    tech_path.write_text("technical volume context", encoding="utf-8")
    letter_path.write_text("generic support letter text", encoding="utf-8")

    technical = analyze_document_mock(type("Record", (), tech_record)(), run_id)
    support = analyze_document_mock(type("Record", (), letter_record)(), run_id)
    support.document_identity.document_category = DocumentCategory.unknown
    support.document_identity.document_role = DocumentRole.unknown
    support.document_identity.origin_type = OriginType.unknown
    support.confidence.document_category = 0.2
    support.confidence.document_role = 0.2
    support.confidence.origin_type = 0.2
    support.confidence.include_in_future_rag = 0.2

    store.write_document_metadata(technical, append_jsonl=False)
    store.write_document_metadata(support, append_jsonl=False)
    store.write_document_metadata_jsonl([technical, support])
    return run_dir, technical.document_id, support.document_id


def test_build_branch_context_packet_uses_neighbor_documents(tmp_path: Path) -> None:
    run_dir, tech_id, support_id = _write_metadata_run(tmp_path / "run_pass2_context")
    store = MetadataStore(run_dir)
    metadata_by_id = store.load_document_metadata_by_id()

    packet = build_branch_context_packet(
        metadata_by_id[support_id],
        list(metadata_by_id.values()),
        threshold=0.65,
    )

    assert packet["branch_context"]["proposal_branch"] == "2025 Fake DOE SBIR Battery Project"
    assert any(doc["document_id"] == tech_id for doc in packet["high_confidence_documents"])


def test_run_two_pass_review_improves_ambiguous_letter_in_mock_mode(tmp_path: Path) -> None:
    run_dir, _tech_id, support_id = _write_metadata_run(tmp_path / "run_pass2_mock")

    result = run_two_pass_review(
        run_dir,
        run_dir.name,
        load_runtime_config(),
        use_mock=True,
    )

    support = result.documents_by_id[support_id]
    report_rows = list(
        csv.DictReader((run_dir / "reports" / "pass2_changes.csv").open(encoding="utf-8"))
    )

    assert result.reviewed_count >= 1
    assert support.system.processing_status == ProcessingStatus.processed_pass2
    assert support.document_identity.document_category == DocumentCategory.partner_document
    assert support.document_identity.document_role == DocumentRole.letter_of_support
    assert support.document_identity.origin_type == OriginType.generated_response
    assert support.confidence.document_category >= 0.9
    assert any(row["field_path"] == "document_identity.document_category" for row in report_rows)
    metadata_json = json.loads(
        (run_dir / "document_metadata" / "by_document_id" / f"{support_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(metadata_json["metadata_history"]) == 3


def test_merge_pass2_candidate_replaces_uncertainties(tmp_path: Path) -> None:
    """Pass 2's uncertainty assessment must not be silently discarded during merge."""
    run_dir, _tech_id, support_id = _write_metadata_run(tmp_path / "run_pass2_uncertainty")
    store = MetadataStore(run_dir)
    pass1_metadata = store.load_document_metadata_by_id()[support_id]
    assert pass1_metadata.uncertainties == []

    pass2_candidate = pass1_metadata.model_copy(
        update={
            "uncertainties": [
                Uncertainty(
                    field="proposal_context.award_status",
                    scope="proposal",
                    confidence=0.6,
                    downstream_impact="critical",
                    reason_unresolved="Award status could not be confirmed from branch context.",
                )
            ]
        }
    )

    merged, changes = _merge_pass2_candidate(pass1_metadata, pass2_candidate, threshold=0.65)

    assert len(merged.uncertainties) == 1
    assert merged.uncertainties[0].downstream_impact == "critical"
    assert any(change["field_path"] == "uncertainties" for change in changes)


def test_run_two_pass_review_does_not_repeat_processed_pass2(tmp_path: Path) -> None:
    run_dir, _tech_id, _support_id = _write_metadata_run(tmp_path / "run_pass2_idempotent")

    first = run_two_pass_review(
        run_dir,
        run_dir.name,
        load_runtime_config(),
        use_mock=True,
    )
    second = run_two_pass_review(
        run_dir,
        run_dir.name,
        load_runtime_config(),
        use_mock=True,
    )

    assert first.reviewed_count >= 1
    assert second.reviewed_count == 0
