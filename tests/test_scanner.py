"""Tests for the scan inventory stage."""

from __future__ import annotations

import csv
import json
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from proposal_ingest.scanner import scan_source_root
from proposal_ingest.schemas import InventoryRecord, RunManifest


def _write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_scan_detects_year_folders() -> None:
    """Year folders (four-digit names) should be detected under the source root."""
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_root = root / "source"
        output_root = root / "output"
        _write_text_file(source_root / "2025" / "Proposal A" / "Technical Volume.pdf", "alpha")
        _write_text_file(source_root / "misc" / "ignored.txt", "misc")

        artifacts = scan_source_root(source_root, output_root)

        assert len(artifacts.inventory_records) == 1
        assert artifacts.inventory_records[0].year_folder == "2025"


def test_scan_finds_proposal_branches() -> None:
    """Each immediate child of a year folder is one proposal branch."""
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_root = root / "source"
        output_root = root / "output"
        _write_text_file(source_root / "2025" / "Proposal A" / "a.pdf", "alpha")
        _write_text_file(source_root / "2025" / "Proposal B" / "b.pdf", "beta")

        artifacts = scan_source_root(source_root, output_root)

        proposal_branches = {record.proposal_branch for record in artifacts.inventory_records}
        assert proposal_branches == {"Proposal A", "Proposal B"}


def test_scan_ignores_stray_year_files() -> None:
    """Files directly under a year folder are ignored and logged to stray_files_ignored.csv."""
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_root = root / "source"
        output_root = root / "output"
        _write_text_file(source_root / "2025" / "readme.txt", "stray")
        _write_text_file(source_root / "2025" / "Proposal A" / "a.pdf", "alpha")

        artifacts = scan_source_root(source_root, output_root)

        assert len(artifacts.stray_files) == 1
        with artifacts.stray_files_csv.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        assert rows[0]["reason"] == "ignored_stray_year_file"


def test_scan_skips_hidden_files() -> None:
    """Hidden/system files should be skipped."""
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_root = root / "source"
        output_root = root / "output"
        _write_text_file(source_root / "2025" / "Proposal A" / ".hidden.pdf", "hidden")
        _write_text_file(source_root / "2025" / "Proposal A" / "visible.pdf", "visible")

        artifacts = scan_source_root(source_root, output_root)

        relative_paths = {record.relative_path for record in artifacts.inventory_records}
        assert "2025/Proposal A/.hidden.pdf" not in relative_paths
        assert "2025/Proposal A/visible.pdf" in relative_paths


def test_scan_skips_temp_office_files() -> None:
    """Temporary Office files beginning with ~$ should be skipped."""
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_root = root / "source"
        output_root = root / "output"
        _write_text_file(source_root / "2025" / "Proposal A" / "~$Draft.docx", "temp")
        _write_text_file(source_root / "2025" / "Proposal A" / "Draft.docx", "real")

        artifacts = scan_source_root(source_root, output_root)

        file_names = {record.file_name_original for record in artifacts.inventory_records}
        assert "~$Draft.docx" not in file_names
        assert "Draft.docx" in file_names


def test_scan_computes_sha256() -> None:
    """Each inventory record should include a valid SHA-256 hash."""
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_root = root / "source"
        output_root = root / "output"
        content = "technical volume"
        _write_text_file(source_root / "2025" / "Proposal A" / "Technical Volume.pdf", content)

        artifacts = scan_source_root(source_root, output_root)

        expected = sha256(content.encode("utf-8")).hexdigest()
        assert artifacts.inventory_records[0].sha256 == expected
        assert artifacts.inventory_records[0].document_id == f"doc_{expected[:16]}"


def test_scan_writes_csv_and_jsonl() -> None:
    """Scan should write both file_inventory.csv and file_inventory.jsonl."""
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_root = root / "source"
        output_root = root / "output"
        _write_text_file(source_root / "2025" / "Proposal A" / "Technical Volume.pdf", "alpha")
        _write_text_file(source_root / "2025" / "Proposal A" / "Slides.pptx", "ppt")

        artifacts = scan_source_root(source_root, output_root)

        assert artifacts.inventory_csv.exists()
        assert artifacts.inventory_jsonl.exists()
        assert artifacts.powerpoint_questions_jsonl.exists()
        assert artifacts.run_manifest_path.exists()
        with artifacts.inventory_jsonl.open(encoding="utf-8") as handle:
            rows = [
                InventoryRecord.model_validate(json.loads(line))
                for line in handle
                if line.strip()
            ]
        assert len(rows) == 2
        with artifacts.run_manifest_path.open(encoding="utf-8") as handle:
            manifest = RunManifest.model_validate(json.load(handle))
        assert manifest.command == "scan"
        with artifacts.powerpoint_questions_jsonl.open(encoding="utf-8") as handle:
            questions = [json.loads(line) for line in handle if line.strip()]
        assert len(questions) == 1


def test_scan_does_not_modify_source() -> None:
    """Source files must never be modified."""
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_root = root / "source"
        output_root = root / "output"
        file_path = source_root / "2025" / "Proposal A" / "Technical Volume.pdf"
        _write_text_file(file_path, "alpha")
        before = file_path.read_bytes()

        scan_source_root(source_root, output_root)

        assert file_path.read_bytes() == before


def test_scan_marks_same_stem_powerpoint_as_superseded() -> None:
    """Same-stem PowerPoints should point to the sibling PDF document ID."""
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_root = root / "source"
        output_root = root / "output"
        branch = source_root / "2025" / "Proposal A"
        _write_text_file(branch / "Slides.pdf", "pdf")
        _write_text_file(branch / "Slides.pptx", "ppt")

        artifacts = scan_source_root(source_root, output_root)

        records_by_extension = {
            record.extension: record for record in artifacts.inventory_records
        }
        assert records_by_extension[".pptx"].processing_status == "superseded_by_pdf"
        assert (
            records_by_extension[".pptx"].superseded_by_document_id
            == records_by_extension[".pdf"].document_id
        )


def test_scan_writes_runs_under_logs_directory() -> None:
    """Non-empty scans should keep their run directory under the logs folder."""
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_root = root / "source"
        output_root = root / "output"
        _write_text_file(source_root / "2025" / "Proposal A" / "Technical Volume.pdf", "alpha")

        artifacts = scan_source_root(source_root, output_root)

        assert artifacts.run_dir.parent == output_root / "logs"
        assert artifacts.run_dir.exists()


def test_scan_dry_run_does_not_write_outputs() -> None:
    """Dry runs should validate records without writing any output."""
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_root = root / "source"
        output_root = root / "output"
        _write_text_file(source_root / "2025" / "Proposal A" / "Technical Volume.pdf", "alpha")

        artifacts = scan_source_root(source_root, output_root, dry_run=True)

        assert len(artifacts.inventory_records) == 1
        assert artifacts.wrote_outputs is False
        assert not artifacts.run_dir.exists()
        assert not (output_root / "logs").exists()


def test_scan_can_prune_empty_run_directories() -> None:
    """Empty scans should be pruned when pruning is enabled."""
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_root = root / "source"
        output_root = root / "output"
        (source_root / "2025").mkdir(parents=True)

        artifacts = scan_source_root(source_root, output_root, prune_empty_runs=True)

        assert artifacts.pruned_run_dir is True
        assert not artifacts.run_dir.exists()


def test_scan_can_keep_empty_run_directories() -> None:
    """Empty scan runs should remain when pruning is explicitly disabled."""
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_root = root / "source"
        output_root = root / "output"
        (source_root / "2025").mkdir(parents=True)

        artifacts = scan_source_root(source_root, output_root, prune_empty_runs=False)

        assert artifacts.pruned_run_dir is False
        assert artifacts.run_dir.exists()
