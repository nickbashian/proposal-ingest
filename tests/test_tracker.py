"""Tests for Phase 10 tracker ingestion, matching, and override behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from proposal_ingest.analyzer import analyze_inventory
from proposal_ingest.config import load_runtime_config
from proposal_ingest.scanner import scan_source_root
from proposal_ingest.schemas import DocumentMetadata
from proposal_ingest.tracker import (
    _rows_from_dataframe,
    apply_tracker_overrides,
    load_tracker_rows,
    match_tracker_row,
)
from tests.test_metadata_validation import make_valid_document_metadata


def _write_tracker_workbook(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_excel(path, index=False)


def test_tracker_parser_and_match_uses_fake_fixture() -> None:
    fixture = (
        Path(__file__).resolve().parents[1]
        / "sample_data"
        / "fake_source_root"
        / "General"
        / "Empower Grant Activities"
        / "Grants In Progress"
        / "fake_grants_tracker.xlsx"
    )
    rows = load_tracker_rows(fixture)
    assert len(rows) == 1
    assert rows[0].proposal_name == "2025 Fake DOE SBIR Battery Project"

    match = match_tracker_row("2025 Fake DOE SBIR Battery Project", rows)
    assert match.status == "matched"
    assert match.tracker_row is not None


def test_tracker_overrides_high_authority_fields_and_logs_name_disagreement(tmp_path: Path) -> None:
    metadata = DocumentMetadata.model_validate(make_valid_document_metadata())
    payload = metadata.model_dump(mode="json")
    payload["proposal_context"]["canonical_proposal_name"] = "Different Canonical Name"
    payload["proposal_context"]["submission_date"] = "2025-01-01"
    payload["proposal_context"]["response_date"] = "2025-02-01"
    payload["proposal_context"]["status"] = "drafted"
    payload["proposal_context"]["award_status"] = "pending"
    metadata = DocumentMetadata.model_validate(payload)

    tracker_row = {
        "proposal_name": "2025 Fake DOE SBIR Battery Project",
        "submission_due_date": "2025-08-15",
        "selection_notification_date": "2025-10-01",
        "status": "awarded",
        "award_status": "selected",
    }
    tracker_path = tmp_path / "tmp_tracker_for_override.xlsx"
    _write_tracker_workbook(tracker_path, [tracker_row])
    rows = load_tracker_rows(tracker_path)

    match = match_tracker_row("2025 Fake DOE SBIR Battery Project", rows)
    assert match.status == "matched"

    updated = apply_tracker_overrides(metadata, match)
    assert updated.proposal_context.submission_date == "2025-08-15"
    assert updated.proposal_context.response_date == "2025-10-01"
    assert updated.proposal_context.status == "awarded"
    assert updated.proposal_context.award_status == "selected"
    assert updated.tracker_matching.tracker_match_status == "matched"
    assert updated.tracker_matching.tracker_row_id is not None
    disagreement_fields = {d["field"] for d in updated.tracker_matching.tracker_disagreements}
    assert "canonical_proposal_name" in disagreement_fields


def test_scan_and_analyze_apply_tracker_rows(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    output_root = tmp_path / "output"
    branch = source_root / "2025" / "2025 Fake DOE SBIR Battery Project"
    branch.mkdir(parents=True)
    (branch / "Technical Volume FINAL.docx").write_text("hello world", encoding="utf-8")

    tracker_path = tmp_path / "fake_tracker.xlsx"
    _write_tracker_workbook(
        tracker_path,
        [
            {
                "proposal_name": "2025 Fake DOE SBIR Battery Project",
                "submission_date": "2025-08-15",
                "selection_notification_date": "2025-10-01",
                "status": "submitted",
                "award_status": "unknown",
            }
        ],
    )

    artifacts = scan_source_root(source_root, output_root, tracker_path=tracker_path)
    assert artifacts.tracker_rows_jsonl.exists()
    assert artifacts.tracker_row_count == 1

    runtime_cfg = load_runtime_config(None, overrides={"processing": {"pass2_enabled": False}})
    results = analyze_inventory(
        artifacts.run_dir,
        artifacts.inventory_records,
        artifacts.run_id,
        use_mock=True,
        config=runtime_cfg,
    )
    assert len(results) == 1
    assert results[0].proposal_context.submission_date == "2025-08-15"
    assert results[0].proposal_context.response_date == "2025-10-01"
    assert results[0].proposal_context.status == "submitted"
    assert results[0].tracker_matching.tracker_match_status == "matched"

    by_id_path = (
        artifacts.run_dir
        / "document_metadata"
        / "by_document_id"
        / f"{results[0].document_id}.json"
    )
    saved = json.loads(by_id_path.read_text(encoding="utf-8"))
    assert saved["tracker_matching"]["tracker_match_status"] == "matched"


def test_rows_from_dataframe_skips_missing_headers_and_uniquifies_duplicates() -> None:
    dataframe = pd.DataFrame(
        [["Proposal A", "ignored", "Proposal A duplicate"]],
        columns=["proposal_name", float("nan"), "proposal_name"],
    )

    rows = _rows_from_dataframe(Path("/tmp/unused.xlsx"), "Tracker", dataframe)

    assert len(rows) == 1
    assert rows[0].values["proposal_name"] == "Proposal A"
    assert rows[0].values["proposal_name_2"] == "Proposal A duplicate"
    assert "nan" not in rows[0].values
