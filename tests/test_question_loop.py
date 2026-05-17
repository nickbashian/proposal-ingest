"""Placeholder tests for the human review question loop.

Implement these tests in Phase 8 alongside question_loop.py.
See docs/07_human_review_workflow.md for the full workflow.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="question_loop not yet implemented — Phase 8")
def test_questions_export_produces_csv() -> None:
    """The question export step should produce a review CSV."""


@pytest.mark.skip(reason="question_loop not yet implemented — Phase 8")
def test_apply_answers_updates_metadata() -> None:
    """Applying answers should update stored metadata deterministically."""


@pytest.mark.skip(reason="question_loop not yet implemented — Phase 8")
def test_question_ids_are_stable_across_runs() -> None:
    """Question IDs should remain stable across repeated exports."""
