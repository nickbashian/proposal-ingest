"""Regression checks for the checked-in synthetic sample documents."""

from __future__ import annotations

from pathlib import Path
from zipfile import is_zipfile

from proposal_ingest.extractors import count_excel_nonempty_cells, extract_text

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_FIXTURE_DIR = (
    REPO_ROOT / "sample_data" / "fake_source_root" / "2025" / "2025 Fake DOE SBIR Battery Project"
)
TRACKER_FIXTURE = (
    REPO_ROOT
    / "sample_data"
    / "fake_source_root"
    / "General"
    / "Empower Grant Activities"
    / "Grants In Progress"
    / "fake_grants_tracker.xlsx"
)


def test_sample_processing_fixtures_have_extractable_content() -> None:
    """The checked-in fake docs should be parser-readable, not placeholder bytes."""
    for fixture_name in [
        "Quad Chart.pdf",
        "FOA Instructions.pdf",
        "Technical Volume FINAL.docx",
        "Support Letter.docx",
        "Budget.xlsx",
    ]:
        extracted = extract_text(PROJECT_FIXTURE_DIR / fixture_name)
        assert extracted.strip(), fixture_name


def test_sample_excel_fixtures_have_nonempty_cells() -> None:
    """The fake workbook fixtures should remain valid spreadsheets with content."""
    for path in [PROJECT_FIXTURE_DIR / "Budget.xlsx", TRACKER_FIXTURE]:
        sheet_count, nonempty_cells = count_excel_nonempty_cells(path)
        assert sheet_count >= 1
        assert nonempty_cells >= 2


def test_sample_powerpoint_fixture_is_a_real_pptx_container() -> None:
    """The fake PowerPoint should be a real OOXML zip container."""
    assert is_zipfile(PROJECT_FIXTURE_DIR / "Quad Chart.pptx")
