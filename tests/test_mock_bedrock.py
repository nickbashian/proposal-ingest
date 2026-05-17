"""Tests for Phase 4 — Mock Bedrock analysis mode."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from typer.testing import CliRunner

from proposal_ingest.analyzer import (
    analyze_inventory,
)
from proposal_ingest.cli import app
from proposal_ingest.mock_bedrock import analyze_document_mock
from proposal_ingest.scanner import scan_source_root
from proposal_ingest.schemas import (
    DocumentCategory,
    DocumentMetadata,
    DocumentRole,
    InventoryRecord,
    ProcessingStatus,
)

_runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_text_file(path: Path, content: str = "fake content") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_fake_inventory_record(
    file_name: str = "Technical Volume.pdf",
    *,
    eligible: bool = True,
    extension: str = ".pdf",
) -> InventoryRecord:
    """Build a minimal valid InventoryRecord for unit tests."""
    sha = hashlib.sha256(file_name.encode()).hexdigest()
    return InventoryRecord(
        document_id=f"doc_{sha[:16]}",
        proposal_id="prop_2025-test__abcd1234",
        source_path=f"C:/source/2025/Test Proposal/{file_name}",
        relative_path=f"2025/Test Proposal/{file_name}",
        year_folder="2025",
        proposal_branch="Test Proposal",
        file_name_original=file_name,
        file_name_safe=file_name.replace(" ", "_"),
        extension=extension,
        size_bytes=1024,
        modified_time="2026-05-16T12:00:00+00:00",
        sha256=sha,
        eligible_for_processing=eligible,
        processing_strategy="direct_bedrock" if eligible else "inventory_only",
        processing_status="pending_analysis" if eligible else "inventory_only",
        skip_reason=None if eligible else "unsupported_file_type",
    )


# ---------------------------------------------------------------------------
# Unit tests: analyze_document_mock
# ---------------------------------------------------------------------------


def test_mock_returns_valid_document_metadata() -> None:
    """Mock analyzer should return schema-valid DocumentMetadata."""
    record = _make_fake_inventory_record("Technical Volume.pdf")
    result = analyze_document_mock(record, "run_test_001")

    assert isinstance(result, DocumentMetadata)
    assert result.document_id == record.document_id
    assert result.run_id == "run_test_001"
    assert result.system.processing_status == ProcessingStatus.processed_pass1


def test_mock_includes_generated_by_marker() -> None:
    """processing_notes must contain 'generated_by: mock_bedrock'."""
    record = _make_fake_inventory_record("Budget Justification.xlsx")
    result = analyze_document_mock(record, "run_test_002")

    assert "generated_by: mock_bedrock" in result.processing_notes


def test_mock_is_deterministic() -> None:
    """Same input must always produce the same output."""
    record = _make_fake_inventory_record("Statement of Work.docx")
    r1 = analyze_document_mock(record, "run_abc")
    r2 = analyze_document_mock(record, "run_abc")

    assert r1.model_dump() == r2.model_dump()


def test_mock_infers_budget_category_from_filename() -> None:
    """'Budget' in filename should yield budget_financial category."""
    record = _make_fake_inventory_record("Budget.xlsx", extension=".xlsx")
    result = analyze_document_mock(record, "run_x")

    assert result.document_identity.document_category == DocumentCategory.budget_financial


def test_mock_infers_proposal_response_category_from_pdf() -> None:
    """A PDF with 'technical' in the stem should be proposal_response."""
    record = _make_fake_inventory_record("Technical Narrative.pdf", extension=".pdf")
    result = analyze_document_mock(record, "run_x")

    assert result.document_identity.document_category == DocumentCategory.proposal_response


def test_mock_infers_rfp_category_from_solicitation_keyword() -> None:
    """'FOA' in filename should yield opportunity_document category."""
    record = _make_fake_inventory_record("FOA Announcement.pdf", extension=".pdf")
    result = analyze_document_mock(record, "run_x")

    assert result.document_identity.document_category == DocumentCategory.opportunity_document


def test_mock_infers_letter_of_support_role() -> None:
    """'letter' in filename should yield letter_of_support role."""
    record = _make_fake_inventory_record("Partner Letter of Support.pdf", extension=".pdf")
    result = analyze_document_mock(record, "run_x")

    assert result.document_identity.document_role == DocumentRole.letter_of_support


def test_mock_infers_abstract_role() -> None:
    """'Abstract' in filename should yield abstract role."""
    record = _make_fake_inventory_record("Abstract.docx")
    result = analyze_document_mock(record, "run_x")

    assert result.document_identity.document_role == DocumentRole.abstract


def test_mock_confidence_values_are_low_to_moderate() -> None:
    """All confidence scores should be ≤ 0.50 in mock mode (low/moderate)."""
    record = _make_fake_inventory_record("Random File.pdf")
    result = analyze_document_mock(record, "run_x")

    for field, value in result.confidence.model_dump().items():
        assert value <= 0.50, f"Confidence field '{field}' = {value} exceeds 0.50"


def test_mock_ineligible_record_excluded_from_rag() -> None:
    """Ineligible records should not be included in clean set or RAG."""
    record = _make_fake_inventory_record("Image.png", eligible=False, extension=".png")
    result = analyze_document_mock(record, "run_x")

    assert result.inclusion.include_in_clean_set is False
    assert result.inclusion.include_in_future_rag is False
    assert result.inclusion.exclude_reason is not None


def test_mock_infers_doe_agency_from_branch_name() -> None:
    """Branch name containing 'DOE' should set agency to DOE."""
    sha = hashlib.sha256(b"x").hexdigest()
    record = InventoryRecord(
        document_id=f"doc_{sha[:16]}",
        proposal_id="prop_test__abc",
        source_path="C:/source/2025/DOE SBIR Phase I/doc.pdf",
        relative_path="2025/DOE SBIR Phase I/doc.pdf",
        year_folder="2025",
        proposal_branch="DOE SBIR Phase I",
        file_name_original="doc.pdf",
        file_name_safe="doc.pdf",
        extension=".pdf",
        size_bytes=100,
        modified_time="2026-01-01T00:00:00+00:00",
        sha256=sha,
        eligible_for_processing=True,
        processing_strategy="direct_bedrock",
        processing_status="pending_analysis",
    )
    result = analyze_document_mock(record, "run_x")

    assert str(result.proposal_context.agency) == "DOE"


# ---------------------------------------------------------------------------
# Integration tests: scan + analyze pipeline (mock mode)
# ---------------------------------------------------------------------------


def test_scan_then_analyze_mock_produces_metadata_files() -> None:
    """Running scan then analyze_inventory in mock mode creates JSON metadata files."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "source"
        output = root / "output"

        _write_text_file(source / "2025" / "Battery SBIR" / "Technical Volume.pdf", "tv content")
        _write_text_file(source / "2025" / "Battery SBIR" / "Budget.xlsx", "budget content")

        artifacts = scan_source_root(source, output)
        assert len(artifacts.inventory_records) == 2

        results = analyze_inventory(
            artifacts.run_dir,
            artifacts.inventory_records,
            artifacts.run_id,
            use_mock=True,
        )

        assert len(results) == 2
        by_id_dir = artifacts.run_dir / "document_metadata" / "by_document_id"
        json_files = list(by_id_dir.glob("*.json"))
        assert len(json_files) == 2


def test_analyze_inventory_skips_ineligible_records() -> None:
    """analyze_inventory should only process eligible records."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "source"
        output = root / "output"

        _write_text_file(source / "2025" / "Proj" / "doc.pdf")
        _write_text_file(source / "2025" / "Proj" / "image.png")

        artifacts = scan_source_root(source, output)
        results = analyze_inventory(
            artifacts.run_dir,
            artifacts.inventory_records,
            artifacts.run_id,
            use_mock=True,
        )

        # Only the PDF is eligible
        assert len(results) == 1
        assert results[0].system.file_name_original == "doc.pdf"


def test_analyze_inventory_output_validates_as_document_metadata() -> None:
    """Each JSON file written by analyze_inventory must parse as DocumentMetadata."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "source"
        output = root / "output"

        _write_text_file(source / "2025" / "Proj" / "Technical Volume.pdf")

        artifacts = scan_source_root(source, output)
        analyze_inventory(
            artifacts.run_dir, artifacts.inventory_records, artifacts.run_id, use_mock=True
        )

        by_id_dir = artifacts.run_dir / "document_metadata" / "by_document_id"
        for json_path in by_id_dir.glob("*.json"):
            raw = json.loads(json_path.read_text(encoding="utf-8"))
            DocumentMetadata.model_validate(raw)  # must not raise


def test_all_document_metadata_jsonl_is_written() -> None:
    """analyze_inventory should append records to all_document_metadata.jsonl."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "source"
        output = root / "output"

        _write_text_file(source / "2025" / "Proj" / "a.pdf", "first document")
        _write_text_file(source / "2025" / "Proj" / "b.docx", "second document")

        artifacts = scan_source_root(source, output)
        analyze_inventory(
            artifacts.run_dir, artifacts.inventory_records, artifacts.run_id, use_mock=True
        )

        jsonl_path = artifacts.run_dir / "document_metadata" / "all_document_metadata.jsonl"
        assert jsonl_path.exists()
        lines = [ln for ln in jsonl_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 2


def test_real_bedrock_path_logs_per_file_errors_without_raising(tmp_path: Path) -> None:
    """Real batch mode should log per-file errors and continue."""
    record = _make_fake_inventory_record("a.pdf")
    record.source_path = str(tmp_path / "missing.pdf")  # type: ignore[misc]

    results = analyze_inventory(tmp_path, [record], "run_x", use_mock=False)

    assert results == []
    assert (tmp_path / "document_metadata" / "failures" / f"{record.document_id}.json").exists()


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


def test_cli_run_all_mock_bedrock() -> None:
    """'run-all --mock-bedrock' should produce end-to-end output without AWS."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "source"
        output = root / "output"

        _write_text_file(source / "2025" / "Proj" / "Technical Volume.pdf")

        result = _runner.invoke(
            app,
            [
                "run-all",
                "--source-root",
                str(source),
                "--output-root",
                str(output),
                "--mock-bedrock",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Scan complete" in result.output
        assert "Analyze complete" in result.output

        # Verify at least one metadata JSON was written
        json_files = list((output / "logs").rglob("document_metadata/by_document_id/*.json"))
        assert len(json_files) >= 1

        manifest_files = list((output / "logs").rglob("run_manifest.json"))
        assert len(manifest_files) == 1
        manifest = json.loads(manifest_files[0].read_text(encoding="utf-8"))
        assert manifest["command"] == "run-all"
        assert manifest["mock_bedrock"] is True


def test_cli_analyze_mock_bedrock_reads_latest_run() -> None:
    """'analyze --mock-bedrock' reads the most recent scan inventory and processes it."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "source"
        output = root / "output"

        _write_text_file(source / "2025" / "Proj" / "Budget Narrative.docx")

        # Run scan first
        scan_result = _runner.invoke(
            app,
            [
                "scan",
                "--source-root",
                str(source),
                "--output-root",
                str(output),
            ],
        )
        assert scan_result.exit_code == 0

        # Now analyze
        result = _runner.invoke(
            app,
            [
                "analyze",
                "--output-root",
                str(output),
                "--mock-bedrock",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Analyze complete" in result.output


def test_cli_process_file_mock_bedrock(tmp_path: Path) -> None:
    """'process-file --mock-bedrock' creates a run dir with metadata."""
    doc = tmp_path / "Proposal Narrative.pdf"
    doc.write_text("fake content", encoding="utf-8")
    output = tmp_path / "output"

    result = _runner.invoke(
        app,
        [
            "process-file",
            "--file",
            str(doc),
            "--output-root",
            str(output),
            "--mock-bedrock",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "process-file complete" in result.output

    json_files = list(output.rglob("document_metadata/by_document_id/*.json"))
    assert len(json_files) == 1
    raw = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert "generated_by: mock_bedrock" in raw.get("processing_notes", [])


def test_cli_analyze_without_mock_bedrock_exits_nonzero() -> None:
    """'analyze' without --mock-bedrock should exit with a non-zero code."""
    with TemporaryDirectory() as tmp:
        result = _runner.invoke(
            app,
            ["analyze", "--output-root", tmp],
        )
        assert result.exit_code != 0
