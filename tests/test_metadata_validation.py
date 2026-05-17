"""Placeholder tests for Pydantic metadata schema validation.

Implement these tests in Phase 3 alongside schemas.py.
See docs/11_copilot_agent_prompts.md (Prompt 4) for acceptance criteria.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="schemas not yet implemented — Phase 3")
def test_valid_document_metadata_passes() -> None:
    """A valid document metadata dict should deserialize without errors."""
    pass


@pytest.mark.skip(reason="schemas not yet implemented — Phase 3")
def test_invalid_document_metadata_raises() -> None:
    """Missing required fields should raise a validation error."""
    pass


@pytest.mark.skip(reason="schemas not yet implemented — Phase 3")
def test_valid_folder_metadata_passes() -> None:
    """A valid folder metadata dict should deserialize without errors."""
    pass
