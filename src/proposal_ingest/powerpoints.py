"""Handle PowerPoint same-stem PDF supersession and review questions."""

from __future__ import annotations

from collections.abc import MutableSequence
from pathlib import PurePosixPath
from typing import Any

from proposal_ingest.file_filters import POWERPOINT_EXTENSIONS
from proposal_ingest.path_utils import short_hash


def apply_powerpoint_rules(records: MutableSequence[dict[str, Any]]) -> list[dict[str, str]]:
    """Mark same-stem PowerPoints as superseded and emit review questions when needed."""
    pdf_by_folder_and_stem: dict[tuple[str, str], str] = {}
    for record in records:
        extension = str(record["extension"]).lower()
        if extension != ".pdf":
            continue
        relative_path = PurePosixPath(str(record["relative_path"]))
        pdf_by_folder_and_stem[(str(relative_path.parent), relative_path.stem.lower())] = str(
            record["document_id"]
        )

    questions: list[dict[str, str]] = []
    for record in records:
        extension = str(record["extension"]).lower()
        if extension not in POWERPOINT_EXTENSIONS:
            continue

        relative_path = PurePosixPath(str(record["relative_path"]))
        pdf_document_id = pdf_by_folder_and_stem.get(
            (str(relative_path.parent), relative_path.stem.lower())
        )

        if pdf_document_id:
            record["eligible_for_processing"] = False
            record["processing_strategy"] = "inventory_only"
            record["processing_status"] = "superseded_by_pdf"
            record["skip_reason"] = "superseded_by_pdf"
            record["superseded_by_document_id"] = pdf_document_id
            continue

        questions.append(
            {
                "question_id": f"q_{short_hash(str(relative_path))}",
                "document_id": str(record["document_id"]),
                "proposal_id": str(record["proposal_id"]),
                "source_path": str(record["source_path"]),
                "relative_path": str(record["relative_path"]),
                "question_type": "powerpoint_special_processing",
                "priority": "medium",
                "question_text": (
                    "PowerPoint file has no same-stem PDF. Review whether it needs special "
                    "processing before later pipeline stages."
                ),
            }
        )

    return questions
