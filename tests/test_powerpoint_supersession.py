"""Placeholder tests for PowerPoint/PDF supersession logic.

Implement these tests in Phase 1 alongside powerpoints.py.
See docs/11_copilot_agent_prompts.md (Prompt 3) for acceptance criteria.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="powerpoints not yet implemented — Phase 1")
def test_pptx_with_same_stem_pdf_is_superseded() -> None:
    """A .pptx whose same-stem .pdf exists should be marked superseded_by_pdf."""
    pass


@pytest.mark.skip(reason="powerpoints not yet implemented — Phase 1")
def test_pptx_without_pdf_generates_review_question() -> None:
    """A .pptx without a same-stem PDF should generate a review question."""
    pass


@pytest.mark.skip(reason="powerpoints not yet implemented — Phase 1")
def test_ppt_extension_handled_same_as_pptx() -> None:
    """Legacy .ppt files should follow the same supersession rules as .pptx."""
    pass
