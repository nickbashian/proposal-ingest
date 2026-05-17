"""Determine inventory-time file eligibility and preliminary processing status."""

from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_PROCESSING_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".csv",
    ".txt",
    ".md",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".bmp", ".webp"}
ZIP_EXTENSIONS = {".zip"}
POWERPOINT_EXTENSIONS = {".ppt", ".pptx"}


@dataclass(frozen=True, slots=True)
class FileClassification:
    eligible_for_processing: bool
    processing_strategy: str
    processing_status: str
    skip_reason: str | None = None
    review_question: str | None = None


def is_hidden_or_system(path: Path) -> bool:
    """Return True when a file should be skipped as hidden or system-managed."""
    if any(part.startswith(".") for part in path.parts if part not in {".", ".."}):
        return True

    try:
        attributes = getattr(path.stat(), "st_file_attributes", 0)
    except OSError:
        return False

    hidden_flag = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0)
    system_flag = getattr(stat, "FILE_ATTRIBUTE_SYSTEM", 0)
    return bool(attributes & (hidden_flag | system_flag))


def is_temp_office_file(path: Path) -> bool:
    """Return True for temporary Office lock files such as ~$Draft.docx."""
    return path.name.startswith("~$")


def classify_path(path: Path) -> FileClassification:
    """Classify a file for inventory and later processing decisions."""
    extension = path.suffix.lower()

    if extension in SUPPORTED_PROCESSING_EXTENSIONS:
        strategy = (
            "local_extract_then_bedrock" if extension in {".xls", ".xlsx"} else "direct_bedrock"
        )
        return FileClassification(
            eligible_for_processing=True,
            processing_strategy=strategy,
            processing_status="pending_analysis",
        )

    if extension in IMAGE_EXTENSIONS:
        return FileClassification(
            eligible_for_processing=False,
            processing_strategy="inventory_only",
            processing_status="inventory_only",
            skip_reason="ignored_image",
        )

    if extension in ZIP_EXTENSIONS:
        return FileClassification(
            eligible_for_processing=False,
            processing_strategy="inventory_only",
            processing_status="inventory_only",
            skip_reason="zip_inventory_only",
        )

    if extension in POWERPOINT_EXTENSIONS:
        return FileClassification(
            eligible_for_processing=False,
            processing_strategy="inventory_only",
            processing_status="inventory_only",
            skip_reason="powerpoint_inventory_only",
            review_question="PowerPoint file has no same-stem PDF and may need manual review.",
        )

    return FileClassification(
        eligible_for_processing=False,
        processing_strategy="inventory_only",
        processing_status="inventory_only",
        skip_reason="unsupported_file_type",
    )
