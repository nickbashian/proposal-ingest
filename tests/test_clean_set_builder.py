"""Placeholder tests for the clean set builder.

Implement these tests in Phase 12 alongside clean_set_builder.py.
See docs/11_copilot_agent_prompts.md (Prompt 11) for acceptance criteria.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="clean_set_builder not yet implemented — Phase 12")
def test_clean_set_contains_only_included_files() -> None:
    """The clean set should only include files marked for inclusion."""


@pytest.mark.skip(reason="clean_set_builder not yet implemented — Phase 12")
def test_excluded_files_are_reported_not_copied() -> None:
    """Excluded files should be logged instead of being copied."""


@pytest.mark.skip(reason="clean_set_builder not yet implemented — Phase 12")
def test_filenames_are_sanitized() -> None:
    """Copied files should have sanitized output filenames."""


@pytest.mark.skip(reason="clean_set_builder not yet implemented — Phase 12")
def test_s3_manifest_rows_match_copied_files() -> None:
    """Manifest rows should correspond to the files copied into the clean set."""
