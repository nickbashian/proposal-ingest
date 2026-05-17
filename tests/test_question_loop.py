"""Tests for the Phase 8 human review question loop."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from proposal_ingest.mock_bedrock import analyze_document_mock
from proposal_ingest.question_loop import (
    apply_answers_from_csv,
    export_questions_to_csv,
    stable_question_id,
)
from proposal_ingest.schemas import InventoryRecord, QuestionForUser


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


def _write_run_with_metadata(output_root: Path) -> tuple[Path, InventoryRecord]:
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
    metadata.questions_for_user = [
        QuestionForUser(
            question_id="model_supplied_unstable_id",
            field="version_status",
            question="Is this the final submitted version?",
            priority="high",
            suggested_options=["final", "draft", "unknown"],
            model_guess="unknown",
            answer_type="enum",
        ),
        QuestionForUser(
            question_id="low_priority_id",
            field="topic_title",
            question="What is the exact topic title?",
            priority="low",
            answer_type="string",
        ),
        QuestionForUser(
            question_id="duplicate_id",
            field="version_status",
            question="Is this the final submitted version?",
            priority="high",
            suggested_options=["final", "draft", "unknown"],
            model_guess="unknown",
            answer_type="enum",
        ),
    ]
    (by_id_dir / f"{metadata.document_id}.json").write_text(
        json.dumps(metadata.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "document_metadata" / "all_document_metadata.jsonl").write_text(
        json.dumps(metadata.model_dump(mode="json"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return run_dir, record


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def test_questions_export_produces_csv_dedupes_and_suppresses_low(tmp_path: Path) -> None:
    _run_dir, record = _write_run_with_metadata(tmp_path)

    result = export_questions_to_csv(tmp_path)

    rows = _read_rows(result.questions_csv)
    assert result.exported_count == 1
    assert result.suppressed_count == 1
    assert rows[0]["field"] == "version_status"
    assert rows[0]["question_id"] == stable_question_id(
        record.document_id, "version_status", "Is this the final submitted version?"
    )


def test_question_ids_are_stable_across_runs(tmp_path: Path) -> None:
    _write_run_with_metadata(tmp_path)

    first = _read_rows(export_questions_to_csv(tmp_path).questions_csv)[0]["question_id"]
    second = _read_rows(export_questions_to_csv(tmp_path).questions_csv)[0]["question_id"]

    assert first == second


def test_apply_answers_updates_metadata_and_archives(tmp_path: Path) -> None:
    run_dir, record = _write_run_with_metadata(tmp_path)
    export_result = export_questions_to_csv(tmp_path)
    rows = _read_rows(export_result.questions_csv)
    rows[0]["user_answer"] = "final"
    with export_result.questions_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    result = apply_answers_from_csv(tmp_path, export_result.questions_csv)

    metadata_path = run_dir / "document_metadata" / "by_document_id" / f"{record.document_id}.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert result.applied_count == 1
    assert result.invalid_count == 0
    assert metadata["document_identity"]["version_status"] == "final"
    assert _read_rows(result.archive_csv)[0]["status"] == "applied"


def test_apply_answers_logs_invalid_answers(tmp_path: Path) -> None:
    run_dir, record = _write_run_with_metadata(tmp_path)
    export_result = export_questions_to_csv(tmp_path)
    rows = _read_rows(export_result.questions_csv)
    rows[0]["user_answer"] = "not_a_version"
    with export_result.questions_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    result = apply_answers_from_csv(tmp_path, export_result.questions_csv)

    metadata_path = run_dir / "document_metadata" / "by_document_id" / f"{record.document_id}.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    errors = _read_rows(result.errors_csv)
    assert result.applied_count == 0
    assert result.invalid_count == 1
    assert errors[0]["field"] == "version_status"
    assert metadata["document_identity"]["version_status"] == "unknown"
