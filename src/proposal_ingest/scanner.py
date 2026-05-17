"""Discover proposal branches and build the inventory artifacts for a scan run."""

from __future__ import annotations

import csv
import json
import re
import secrets
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from proposal_ingest.file_filters import (
    classify_path,
    is_hidden_or_system,
    is_temp_office_file,
)
from proposal_ingest.hashing import document_id_from_sha256, sha256_file
from proposal_ingest.metadata_store import MetadataStore
from proposal_ingest.path_utils import proposal_id_from_branch, sanitize_filename
from proposal_ingest.powerpoints import apply_powerpoint_rules
from proposal_ingest.schemas import APP_SCHEMA_VERSION, InventoryRecord, RunManifest
from proposal_ingest.tracker import load_tracker_rows, write_tracker_rows_jsonl

_YEAR_FOLDER_RE = re.compile(r"^20\d{2}$")

INVENTORY_COLUMNS = [
    "document_id",
    "proposal_id",
    "source_path",
    "relative_path",
    "year_folder",
    "proposal_branch",
    "file_name_original",
    "file_name_safe",
    "extension",
    "size_bytes",
    "modified_time",
    "sha256",
    "eligible_for_processing",
    "processing_strategy",
    "processing_status",
    "skip_reason",
    "duplicate_of_document_id",
    "superseded_by_document_id",
]
STRAY_FILE_COLUMNS = ["year_folder", "source_path", "relative_path", "reason"]


@dataclass(slots=True)
class ScanArtifacts:
    run_id: str
    run_dir: Path
    inventory_csv: Path
    inventory_jsonl: Path
    stray_files_csv: Path
    powerpoint_questions_jsonl: Path
    run_manifest_path: Path
    wrote_outputs: bool
    pruned_run_dir: bool
    inventory_records: list[InventoryRecord]
    stray_files: list[dict[str, str]]
    powerpoint_review_questions: list[dict[str, str]]
    tracker_rows_jsonl: Path
    tracker_row_count: int
    tracker_load_error: str | None


def scan_source_root(
    source_root: Path,
    output_root: Path,
    *,
    dry_run: bool = False,
    prune_empty_runs: bool = True,
    tracker_path: Path | None = None,
    tracker_sheet_name: str | None = None,
    tracker_header_row: int = 0,
) -> ScanArtifacts:
    """Scan a source tree and write inventory artifacts under a run-scoped output directory."""
    source_root = source_root.resolve()
    output_root = output_root.resolve()

    if not source_root.exists() or not source_root.is_dir():
        raise ValueError(f"Source root does not exist or is not a directory: {source_root}")

    run_id = _build_run_id()
    run_dir = output_root / "logs" / run_id
    inventory_dir = run_dir / "inventory"
    run_manifest_path = run_dir / "run_manifest.json"

    stray_files: list[dict[str, str]] = []
    inventory_records: list[dict[str, Any]] = []

    for year_dir in _iter_year_folders(source_root):
        year_folder = year_dir.name
        for child in sorted(year_dir.iterdir(), key=lambda path: path.name.lower()):
            if child.is_file():
                stray_files.append(
                    {
                        "year_folder": year_folder,
                        "source_path": str(child),
                        "relative_path": child.relative_to(source_root).as_posix(),
                        "reason": "ignored_stray_year_file",
                    }
                )
                continue

            if not child.is_dir():
                continue

            inventory_records.extend(
                _scan_branch(source_root=source_root, year_dir=year_dir, branch_dir=child)
            )

    _mark_duplicate_records(inventory_records)
    powerpoint_questions = apply_powerpoint_rules(inventory_records)
    validated_inventory_records = [
        InventoryRecord.model_validate(record) for record in inventory_records
    ]

    inventory_csv = inventory_dir / "file_inventory.csv"
    inventory_jsonl = inventory_dir / "file_inventory.jsonl"
    stray_files_csv = inventory_dir / "stray_files_ignored.csv"
    powerpoint_questions_jsonl = inventory_dir / "powerpoint_review_questions.jsonl"
    tracker_rows_jsonl = run_dir / "tracker" / "tracker_rows.jsonl"
    wrote_outputs = False
    pruned_run_dir = False
    tracker_row_count = 0
    tracker_load_error: str | None = None

    if not dry_run:
        inventory_dir.mkdir(parents=True, exist_ok=True)
        _write_csv(inventory_csv, INVENTORY_COLUMNS, validated_inventory_records)
        _write_jsonl(inventory_jsonl, validated_inventory_records)
        _write_csv(stray_files_csv, STRAY_FILE_COLUMNS, stray_files)
        _write_jsonl(powerpoint_questions_jsonl, powerpoint_questions)
        if tracker_path is not None:
            try:
                tracker_rows = load_tracker_rows(
                    tracker_path,
                    sheet_name=tracker_sheet_name,
                    header_row=tracker_header_row,
                )
                tracker_row_count = len(tracker_rows)
                write_tracker_rows_jsonl(tracker_rows, run_dir)
            except Exception as exc:  # non-fatal by design
                tracker_load_error = str(exc)
        MetadataStore(run_dir).write_run_manifest(
            RunManifest(
                schema_version=APP_SCHEMA_VERSION,
                run_id=run_id,
                command="scan",
                source_root=str(source_root),
                output_root=str(output_root),
                config_snapshot={
                    "dry_run": dry_run,
                    "prune_empty_runs": prune_empty_runs,
                    "tracker_path": str(tracker_path) if tracker_path else None,
                    "tracker_sheet_name": tracker_sheet_name,
                    "tracker_header_row": tracker_header_row,
                    "tracker_row_count": tracker_row_count,
                    "tracker_load_error": tracker_load_error,
                },
                git_commit=None,
                timestamp=datetime.now(UTC).isoformat(),
                mock_bedrock=False,
            )
        )
        wrote_outputs = True

    if prune_empty_runs:
        pruned_run_dir = run_dir in _prune_empty_run_dirs(output_root / "logs")

    return ScanArtifacts(
        run_id=run_id,
        run_dir=run_dir,
        inventory_csv=inventory_csv,
        inventory_jsonl=inventory_jsonl,
        stray_files_csv=stray_files_csv,
        powerpoint_questions_jsonl=powerpoint_questions_jsonl,
        run_manifest_path=run_manifest_path,
        wrote_outputs=wrote_outputs,
        pruned_run_dir=pruned_run_dir,
        inventory_records=validated_inventory_records,
        stray_files=stray_files,
        powerpoint_review_questions=powerpoint_questions,
        tracker_rows_jsonl=tracker_rows_jsonl,
        tracker_row_count=tracker_row_count,
        tracker_load_error=tracker_load_error,
    )


def _build_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return f"run_{timestamp}_{secrets.token_hex(3)}"


def _iter_year_folders(source_root: Path) -> list[Path]:
    return [
        child
        for child in sorted(source_root.iterdir(), key=lambda path: path.name.lower())
        if child.is_dir() and _YEAR_FOLDER_RE.match(child.name)
    ]


def _scan_branch(*, source_root: Path, year_dir: Path, branch_dir: Path) -> list[dict[str, Any]]:
    branch_relative_path = branch_dir.relative_to(source_root).as_posix()
    proposal_id = proposal_id_from_branch(
        year_folder=year_dir.name,
        proposal_branch_name=branch_dir.name,
        relative_branch_path=branch_relative_path,
    )

    records: list[dict[str, Any]] = []
    for file_path in sorted(branch_dir.rglob("*"), key=lambda path: path.as_posix().lower()):
        if not file_path.is_file():
            continue
        if is_hidden_or_system(file_path):
            continue
        if is_temp_office_file(file_path):
            continue

        classification = classify_path(file_path)
        file_stat = file_path.stat()
        sha256_hex = sha256_file(file_path)
        records.append(
            {
                "document_id": document_id_from_sha256(sha256_hex),
                "proposal_id": proposal_id,
                "source_path": str(file_path),
                "relative_path": file_path.relative_to(source_root).as_posix(),
                "year_folder": year_dir.name,
                "proposal_branch": branch_dir.name,
                "file_name_original": file_path.name,
                "file_name_safe": sanitize_filename(file_path.name),
                "extension": file_path.suffix.lower(),
                "size_bytes": file_stat.st_size,
                "modified_time": datetime.fromtimestamp(file_stat.st_mtime, tz=UTC).isoformat(),
                "sha256": sha256_hex,
                "eligible_for_processing": classification.eligible_for_processing,
                "processing_strategy": classification.processing_strategy,
                "processing_status": classification.processing_status,
                "skip_reason": classification.skip_reason,
                "duplicate_of_document_id": None,
                "superseded_by_document_id": None,
            }
        )

    return records


def _mark_duplicate_records(records: list[dict[str, Any]]) -> None:
    first_document_id_by_hash: dict[str, str] = {}
    for record in records:
        sha256_hex = str(record["sha256"])
        document_id = str(record["document_id"])
        first_document_id = first_document_id_by_hash.setdefault(sha256_hex, document_id)
        if first_document_id != document_id:
            record["duplicate_of_document_id"] = first_document_id


def _write_csv(
    path: Path, fieldnames: list[str], rows: list[InventoryRecord] | list[dict[str, Any]]
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            row_data = row.model_dump(mode="json") if isinstance(row, InventoryRecord) else row
            writer.writerow({field: row_data.get(field) for field in fieldnames})


def _write_jsonl(path: Path, rows: list[InventoryRecord] | list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            row_data = row.model_dump(mode="json") if isinstance(row, InventoryRecord) else row
            handle.write(json.dumps(row_data, sort_keys=True))
            handle.write("\n")


def _prune_empty_run_dirs(logs_root: Path) -> set[Path]:
    if not logs_root.exists():
        return set()

    pruned_paths: set[Path] = set()
    for run_dir in sorted(logs_root.glob("run_*")):
        if run_dir.is_dir() and _is_empty_run_dir(run_dir):
            shutil.rmtree(run_dir)
            pruned_paths.add(run_dir)
    return pruned_paths


def _is_empty_run_dir(run_dir: Path) -> bool:
    inventory_jsonl = run_dir / "inventory" / "file_inventory.jsonl"
    stray_csv = run_dir / "inventory" / "stray_files_ignored.csv"
    questions_jsonl = run_dir / "inventory" / "powerpoint_review_questions.jsonl"
    all_document_metadata = run_dir / "document_metadata" / "all_document_metadata.jsonl"
    folder_metadata_dir = run_dir / "folder_metadata"

    return (
        _not_has_jsonl_rows(inventory_jsonl)
        and _csv_has_header_only(stray_csv)
        and _not_has_jsonl_rows(questions_jsonl)
        and _not_has_jsonl_rows(all_document_metadata)
        and not any(folder_metadata_dir.glob("*.json"))
    )


def _not_has_jsonl_rows(path: Path) -> bool:
    if not path.exists():
        return True
    with path.open(encoding="utf-8") as handle:
        return not any(line.strip() for line in handle)


def _csv_has_header_only(path: Path) -> bool:
    if not path.exists():
        return True
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        return not any(row for row in reader)
