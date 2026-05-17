"""Placeholder tests for the scanner module.

Implement these tests in Phase 1 alongside scanner.py.
See docs/11_copilot_agent_prompts.md (Prompt 2) for acceptance criteria.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="scanner not yet implemented — Phase 1")
def test_scan_detects_year_folders() -> None:
    """Year folders (four-digit names) should be detected under the source root."""
    pass


@pytest.mark.skip(reason="scanner not yet implemented — Phase 1")
def test_scan_finds_proposal_branches() -> None:
    """Each immediate child of a year folder is one proposal branch."""
    pass


@pytest.mark.skip(reason="scanner not yet implemented — Phase 1")
def test_scan_ignores_stray_year_files() -> None:
    """Files directly under a year folder are ignored and logged to stray_files_ignored.csv."""
    pass


@pytest.mark.skip(reason="scanner not yet implemented — Phase 1")
def test_scan_skips_hidden_files() -> None:
    """Hidden/system files should be skipped."""
    pass


@pytest.mark.skip(reason="scanner not yet implemented — Phase 1")
def test_scan_skips_temp_office_files() -> None:
    """Temporary Office files beginning with ~$ should be skipped."""
    pass


@pytest.mark.skip(reason="scanner not yet implemented — Phase 1")
def test_scan_computes_sha256() -> None:
    """Each inventory record should include a valid SHA-256 hash."""
    pass


@pytest.mark.skip(reason="scanner not yet implemented — Phase 1")
def test_scan_writes_csv_and_jsonl() -> None:
    """Scan should write both file_inventory.csv and file_inventory.jsonl."""
    pass


@pytest.mark.skip(reason="scanner not yet implemented — Phase 1")
def test_scan_does_not_modify_source() -> None:
    """Source files must never be modified."""
    pass
