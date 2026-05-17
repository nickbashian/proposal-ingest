"""Placeholder tests for file filtering logic.

Implement these tests in Phase 1 alongside file_filters.py.
See docs/11_copilot_agent_prompts.md (Prompt 3) for acceptance criteria.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="file_filters not yet implemented — Phase 1")
def test_supported_extensions_are_processable() -> None:
    """PDF, DOCX, XLSX, etc. should be marked as pending_analysis."""
    pass


@pytest.mark.skip(reason="file_filters not yet implemented — Phase 1")
def test_images_are_ignored() -> None:
    """PNG, JPG, TIFF, etc. should be ignored (inventory_only with skip reason)."""
    pass


@pytest.mark.skip(reason="file_filters not yet implemented — Phase 1")
def test_zip_files_are_inventory_only() -> None:
    """ZIP archives should be inventory-only."""
    pass


@pytest.mark.skip(reason="file_filters not yet implemented — Phase 1")
def test_unsupported_types_get_skip_reason() -> None:
    """Unsupported file types should have a skip reason recorded."""
    pass
