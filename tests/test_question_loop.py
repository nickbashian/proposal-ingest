"""Tests for the Phase 8 human review question loop.

Document analysis records material uncertainties for later proposal-level
reconciliation instead of exporting user-facing questions directly, so these
tests confirm the exporter ignores document-level `uncertainties` and legacy
`questions_for_user` entries, and only surfaces explicitly generated
operational questions (for example, unsupported PowerPoint handling).
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from proposal_ingest.human_overrides import load_human_overrides
from proposal_ingest.metadata_store import MetadataStore
from proposal_ingest.mock_bedrock import analyze_document_mock
from proposal_ingest.proposal_synthesizer import build_deterministic_proposal_metadata
from proposal_ingest.question_arbiter import stable_proposal_question_id
from proposal_ingest.question_loop import (
    REVIEW_COLUMNS,
    apply_answers_from_csv,
    export_questions_to_csv,
    stable_question_id,
)
from proposal_ingest.schemas import (
    DocumentMetadata,
    InventoryRecord,
    ProposalMetadata,
    QuestionForUser,
    ReviewQuestion,
    Uncertainty,
)


def _record(file_name: str = "Technical Volume.pdf") -> InventoryRecord:
    sha = hashlib.sha256(file_name.encode()).hexdigest()
    return InventoryRecord(
        document_id=f"doc_{sha[:16]}",
        proposal_id="prop_2025-test__abcd1234",
        source_path=f"/source/2025/Test Proposal/{file_name}",
        relative_path=f"2025/Test Proposal/{file_name}",
        year_folder="2025",
        proposal_branch="Test Proposal",
        file_name_original=file_name,
        file_name_safe=file_name.replace(" ", "_"),
        extension=Path(file_name).suffix.lower(),
        size_bytes=123,
        modified_time="2026-05-16T12:00:00+00:00",
        sha256=sha,
        eligible_for_processing=True,
        processing_strategy="direct_bedrock",
        processing_status="pending_analysis",
    )


def _write_run_with_metadata(
    output_root: Path,
    *,
    metadata_overrides: dict[str, object] | None = None,
) -> tuple[Path, InventoryRecord, DocumentMetadata]:
    run_dir = output_root / "logs" / "run_20260517_120000_abcdef"
    inventory_dir = run_dir / "inventory"
    by_id_dir = run_dir / "document_metadata" / "by_document_id"
    inventory_dir.mkdir(parents=True)
    by_id_dir.mkdir(parents=True)

    record = _record()
    (inventory_dir / "file_inventory.jsonl").write_text(
        json.dumps(record.model_dump(mode="json")) + "\n", encoding="utf-8"
    )
    metadata = analyze_document_mock(record, run_id=run_dir.name)
    if metadata_overrides:
        metadata = metadata.model_copy(update=metadata_overrides)
    (by_id_dir / f"{metadata.document_id}.json").write_text(
        json.dumps(metadata.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "document_metadata" / "all_document_metadata.jsonl").write_text(
        json.dumps(metadata.model_dump(mode="json"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return run_dir, record, metadata


def _write_powerpoint_question(run_dir: Path, record: InventoryRecord) -> None:
    path = run_dir / "inventory" / "powerpoint_review_questions.jsonl"
    payload = {
        "document_id": record.document_id,
        "proposal_id": record.proposal_id,
        "source_path": record.source_path,
        "relative_path": record.relative_path,
        "question_type": "powerpoint_special_processing",
        "priority": "medium",
        "question_text": (
            "PowerPoint file has no same-stem PDF. Review whether it needs special "
            "processing before later pipeline stages."
        ),
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_manual_answers_csv(path: Path, row: dict[str, str]) -> None:
    full_row = {column: "" for column in REVIEW_COLUMNS}
    full_row.update(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerow(full_row)


def test_export_ignores_document_uncertainties(tmp_path: Path) -> None:
    """A clear document with a proposal-scoped uncertainty produces zero CSV rows."""
    _write_run_with_metadata(
        tmp_path,
        metadata_overrides={
            "uncertainties": [
                Uncertainty(
                    field="proposal_context.award_status",
                    scope="proposal",
                    current_guess="awarded",
                    confidence=0.6,
                    evidence=["Folder path contains AWD"],
                    downstream_impact="critical",
                    reason_unresolved="No award notice present in this document.",
                )
            ]
        },
    )

    result = export_questions_to_csv(tmp_path)

    assert result.exported_count == 0
    assert result.suppressed_count == 0
    assert _read_rows(result.questions_csv) == []


def test_export_ignores_legacy_questions_for_user(tmp_path: Path) -> None:
    """Legacy Pass 1 questions_for_user output must not leak into the review CSV."""
    _write_run_with_metadata(
        tmp_path,
        metadata_overrides={
            "questions_for_user": [
                QuestionForUser(
                    question_id="legacy_q_1",
                    field="version_status",
                    question="Is this the final submitted version?",
                    priority="critical",
                    answer_type="enum",
                )
            ]
        },
    )

    result = export_questions_to_csv(tmp_path)

    assert result.exported_count == 0
    assert _read_rows(result.questions_csv) == []


def test_export_still_surfaces_powerpoint_operational_questions(tmp_path: Path) -> None:
    """Explicitly generated operational questions (e.g. PowerPoint review) still export."""
    run_dir, record, _metadata = _write_run_with_metadata(tmp_path)
    _write_powerpoint_question(run_dir, record)

    result = export_questions_to_csv(tmp_path)

    rows = _read_rows(result.questions_csv)
    assert result.exported_count == 1
    assert rows[0]["field"] == "needs_powerpoint_processing"


def test_question_ids_are_stable_across_runs(tmp_path: Path) -> None:
    run_dir, record, _metadata = _write_run_with_metadata(tmp_path)
    _write_powerpoint_question(run_dir, record)

    first = _read_rows(export_questions_to_csv(tmp_path).questions_csv)[0]["question_id"]
    second = _read_rows(export_questions_to_csv(tmp_path).questions_csv)[0]["question_id"]

    assert first == second
    assert first == stable_question_id(
        record.document_id,
        "needs_powerpoint_processing",
        "PowerPoint file has no same-stem PDF. Review whether it needs special "
        "processing before later pipeline stages.",
    )


def test_apply_answers_updates_metadata_and_archives(tmp_path: Path) -> None:
    run_dir, record, _metadata = _write_run_with_metadata(tmp_path)
    answers_csv = tmp_path / "review" / "questions_to_answer.csv"
    _write_manual_answers_csv(
        answers_csv,
        {
            "question_id": "q_manual_1",
            "document_id": record.document_id,
            "proposal_id": record.proposal_id,
            "field": "version_status",
            "answer_type": "enum",
            "user_answer": "final",
            "status": "open",
        },
    )

    result = apply_answers_from_csv(tmp_path, answers_csv)

    metadata_path = run_dir / "document_metadata" / "by_document_id" / f"{record.document_id}.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert result.applied_count == 1
    assert result.invalid_count == 0
    assert metadata["document_identity"]["version_status"] == "final"
    assert _read_rows(result.archive_csv)[0]["status"] == "applied"


def test_apply_answers_logs_invalid_answers(tmp_path: Path) -> None:
    run_dir, record, _metadata = _write_run_with_metadata(tmp_path)
    answers_csv = tmp_path / "review" / "questions_to_answer.csv"
    _write_manual_answers_csv(
        answers_csv,
        {
            "question_id": "q_manual_2",
            "document_id": record.document_id,
            "proposal_id": record.proposal_id,
            "field": "version_status",
            "answer_type": "enum",
            "user_answer": "not_a_version",
            "status": "open",
        },
    )

    result = apply_answers_from_csv(tmp_path, answers_csv)

    metadata_path = run_dir / "document_metadata" / "by_document_id" / f"{record.document_id}.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    errors = _read_rows(result.errors_csv)
    assert result.applied_count == 0
    assert result.invalid_count == 1
    assert errors[0]["field"] == "version_status"
    assert metadata["document_identity"]["version_status"] == "unknown"


# ---------------------------------------------------------------------------
# Proposal-scoped export/apply (issue #8)
# ---------------------------------------------------------------------------


def _write_run_with_two_documents_and_proposal(
    output_root: Path,
) -> tuple[Path, DocumentMetadata, DocumentMetadata, ProposalMetadata]:
    run_dir = output_root / "logs" / "run_20260517_120000_abcdef"
    (run_dir / "inventory").mkdir(parents=True)
    record_a = _record("Doc A.pdf")
    record_b = _record("Doc B.pdf")
    metadata_a = analyze_document_mock(record_a, run_id=run_dir.name)
    metadata_b = analyze_document_mock(record_b, run_id=run_dir.name)
    (run_dir / "inventory" / "file_inventory.jsonl").write_text(
        json.dumps(record_a.model_dump(mode="json"))
        + "\n"
        + json.dumps(record_b.model_dump(mode="json"))
        + "\n",
        encoding="utf-8",
    )

    store = MetadataStore(run_dir)
    store.write_document_metadata(metadata_a, append_jsonl=False)
    store.write_document_metadata(metadata_b, append_jsonl=False)
    store.write_document_metadata_jsonl([metadata_a, metadata_b])

    proposal = build_deterministic_proposal_metadata([metadata_a, metadata_b])
    store.write_proposal_metadata(proposal)
    store.write_proposal_metadata_jsonl([proposal])

    return run_dir, metadata_a, metadata_b, proposal


def test_export_includes_arbitrated_proposal_questions(tmp_path: Path) -> None:
    run_dir, metadata_a, _metadata_b, proposal = _write_run_with_two_documents_and_proposal(
        tmp_path
    )
    store = MetadataStore(run_dir)
    question_id = stable_proposal_question_id(
        proposal.proposal_id, "proposal", "proposal_fact", "award_status"
    )
    store.write_arbitrated_questions(
        [
            ReviewQuestion(
                question_id=question_id,
                proposal_id=proposal.proposal_id,
                field="canonical_identity.award_status",
                question="What is the correct award status?",
                priority="high",
                scope="proposal",
                decision_type="proposal_fact",
                proposal_name=proposal.canonical_identity.proposal_name,
                affected_document_ids=metadata_a.document_id,
                model_confidence=0.4,
                evidence_summary="Documents disagree.",
                why_human_input_is_needed="No tracker match available.",
            )
        ]
    )

    result = export_questions_to_csv(tmp_path)

    rows = _read_rows(result.questions_csv)
    assert result.exported_count == 1
    assert rows[0]["question_id"] == question_id
    assert rows[0]["scope"] == "proposal"
    assert rows[0]["proposal_name"] == proposal.canonical_identity.proposal_name


def test_apply_proposal_scoped_answer_updates_proposal_and_documents(tmp_path: Path) -> None:
    run_dir, metadata_a, metadata_b, proposal = _write_run_with_two_documents_and_proposal(tmp_path)
    question_id = stable_proposal_question_id(
        proposal.proposal_id, "proposal", "proposal_fact", "award_status"
    )
    answers_csv = tmp_path / "review" / "questions_to_answer.csv"
    _write_manual_answers_csv(
        answers_csv,
        {
            "question_id": question_id,
            "proposal_id": proposal.proposal_id,
            "scope": "proposal",
            "decision_type": "proposal_fact",
            "field": "canonical_identity.award_status",
            "affected_document_ids": f"{metadata_a.document_id}|{metadata_b.document_id}",
            "answer_type": "string",
            "user_answer": "awarded",
            "status": "open",
        },
    )

    result = apply_answers_from_csv(tmp_path, answers_csv)

    assert result.applied_count == 1
    assert result.invalid_count == 0

    store = MetadataStore(run_dir)
    updated_proposal = store.load_proposal_metadata_by_id()[proposal.proposal_id]
    assert updated_proposal.canonical_identity.award_status == "awarded"

    documents = store.load_document_metadata_by_id()
    assert documents[metadata_a.document_id].proposal_context.award_status == "awarded"
    assert documents[metadata_b.document_id].proposal_context.award_status == "awarded"

    overrides = load_human_overrides(tmp_path)
    assert len(overrides) == 1
    assert overrides[0].question_id == question_id
    assert overrides[0].applied_value == "awarded"
    assert set(overrides[0].affected_document_ids) == {
        metadata_a.document_id,
        metadata_b.document_id,
    }

    archive_rows = _read_rows(result.archive_csv)
    assert archive_rows[0]["status"] == "applied"


def test_apply_authoritative_document_answer_updates_document_lineage(tmp_path: Path) -> None:
    run_dir, metadata_a, metadata_b, proposal = _write_run_with_two_documents_and_proposal(tmp_path)
    question_id = stable_proposal_question_id(
        proposal.proposal_id, "document_family", "authoritative_document", "authoritative_document"
    )
    answers_csv = tmp_path / "review" / "questions_to_answer.csv"
    _write_manual_answers_csv(
        answers_csv,
        {
            "question_id": question_id,
            "proposal_id": proposal.proposal_id,
            "scope": "document_family",
            "decision_type": "authoritative_document",
            "field": "authoritative_document",
            "affected_document_ids": f"{metadata_a.document_id}|{metadata_b.document_id}",
            "answer_type": "string",
            "user_answer": metadata_a.document_id,
            "status": "open",
        },
    )

    result = apply_answers_from_csv(tmp_path, answers_csv)
    assert result.applied_count == 1

    store = MetadataStore(run_dir)
    updated_proposal = store.load_proposal_metadata_by_id()[proposal.proposal_id]
    lineage_by_id = {entry.document_id: entry for entry in updated_proposal.document_lineage}
    assert lineage_by_id[metadata_a.document_id].is_authoritative is True
    assert lineage_by_id[metadata_b.document_id].is_authoritative is False
    assert lineage_by_id[metadata_b.document_id].superseded_by_document_id == metadata_a.document_id
