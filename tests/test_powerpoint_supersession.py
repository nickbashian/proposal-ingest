"""Tests for PowerPoint same-stem PDF supersession rules."""

from __future__ import annotations

from proposal_ingest.powerpoints import apply_powerpoint_rules


def test_pptx_with_same_stem_pdf_is_superseded() -> None:
    """A .pptx whose same-stem .pdf exists should be marked superseded_by_pdf."""
    records = [
        {
            "document_id": "doc_pdf",
            "proposal_id": "prop_1",
            "source_path": "C:/source/2025/Branch/slides.pdf",
            "relative_path": "2025/Branch/slides.pdf",
            "extension": ".pdf",
        },
        {
            "document_id": "doc_pptx",
            "proposal_id": "prop_1",
            "source_path": "C:/source/2025/Branch/slides.pptx",
            "relative_path": "2025/Branch/slides.pptx",
            "extension": ".pptx",
            "eligible_for_processing": False,
            "processing_strategy": "inventory_only",
            "processing_status": "inventory_only",
            "skip_reason": "powerpoint_inventory_only",
            "superseded_by_document_id": None,
        },
    ]

    questions = apply_powerpoint_rules(records)

    assert not questions
    assert records[1]["processing_status"] == "superseded_by_pdf"
    assert records[1]["superseded_by_document_id"] == "doc_pdf"


def test_pptx_without_pdf_generates_review_question() -> None:
    """A .pptx without a same-stem PDF should generate a review question."""
    records = [
        {
            "document_id": "doc_pptx",
            "proposal_id": "prop_1",
            "source_path": "C:/source/2025/Branch/slides.pptx",
            "relative_path": "2025/Branch/slides.pptx",
            "extension": ".pptx",
            "eligible_for_processing": False,
            "processing_strategy": "inventory_only",
            "processing_status": "inventory_only",
            "skip_reason": "powerpoint_inventory_only",
            "superseded_by_document_id": None,
        }
    ]

    questions = apply_powerpoint_rules(records)

    assert len(questions) == 1
    assert questions[0]["document_id"] == "doc_pptx"
    assert questions[0]["question_type"] == "powerpoint_special_processing"


def test_ppt_extension_handled_same_as_pptx() -> None:
    """Legacy .ppt files should follow the same supersession rules as .pptx."""
    records = [
        {
            "document_id": "doc_pdf",
            "proposal_id": "prop_1",
            "source_path": "C:/source/2025/Branch/slides.pdf",
            "relative_path": "2025/Branch/slides.pdf",
            "extension": ".pdf",
        },
        {
            "document_id": "doc_ppt",
            "proposal_id": "prop_1",
            "source_path": "C:/source/2025/Branch/slides.ppt",
            "relative_path": "2025/Branch/slides.ppt",
            "extension": ".ppt",
            "eligible_for_processing": False,
            "processing_strategy": "inventory_only",
            "processing_status": "inventory_only",
            "skip_reason": "powerpoint_inventory_only",
            "superseded_by_document_id": None,
        },
    ]

    apply_powerpoint_rules(records)

    assert records[1]["processing_status"] == "superseded_by_pdf"
    assert records[1]["superseded_by_document_id"] == "doc_pdf"
