"""Tests for inventory-time file classification rules."""

from __future__ import annotations

from pathlib import Path

from proposal_ingest.file_filters import classify_path


def test_supported_extensions_are_processable() -> None:
    """PDF, DOCX, XLSX, etc. should be marked as pending_analysis."""
    for file_name in [
        "file.pdf",
        "file.docx",
        "file.doc",
        "file.xlsx",
        "file.xls",
        "file.csv",
        "file.txt",
        "file.md",
    ]:
        classification = classify_path(Path(file_name))
        assert classification.eligible_for_processing is True
        assert classification.processing_status == "pending_analysis"


def test_images_are_ignored() -> None:
    """PNG, JPG, TIFF, etc. should be ignored (inventory_only with skip reason)."""
    classification = classify_path(Path("figure.png"))
    assert classification.eligible_for_processing is False
    assert classification.processing_strategy == "inventory_only"
    assert classification.skip_reason == "ignored_image"


def test_zip_files_are_inventory_only() -> None:
    """ZIP archives should be inventory-only."""
    classification = classify_path(Path("archive.zip"))
    assert classification.eligible_for_processing is False
    assert classification.processing_status == "inventory_only"
    assert classification.skip_reason == "zip_inventory_only"


def test_powerpoints_are_inventory_only_with_review_question() -> None:
    """PowerPoints should remain inventory-only and carry a review note."""
    classification = classify_path(Path("slides.pptx"))
    assert classification.eligible_for_processing is False
    assert classification.processing_status == "inventory_only"
    assert classification.review_question is not None


def test_unsupported_types_get_skip_reason() -> None:
    """Unsupported file types should have a skip reason recorded."""
    classification = classify_path(Path("notes.exe"))
    assert classification.eligible_for_processing is False
    assert classification.skip_reason == "unsupported_file_type"
