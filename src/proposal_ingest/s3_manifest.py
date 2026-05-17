"""Generate the local S3 manifest JSONL for future ingestion."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from proposal_ingest.schemas import DocumentMetadata, S3ManifestRow


def build_recommended_s3_key(
    metadata: DocumentMetadata,
    *,
    clean_filename: str,
    base_prefix: str = "proposal-history",
) -> str:
    """Return the future S3 key for a copied clean-set document."""
    parts = [
        base_prefix.strip("/"),
        metadata.system.year_folder,
        metadata.proposal_id,
        "documents",
        clean_filename,
    ]
    return "/".join(part.strip("/") for part in parts if part.strip("/"))


def build_s3_manifest_row(
    metadata: DocumentMetadata,
    *,
    local_clean_path: Path,
    metadata_path: Path,
    clean_filename: str,
    base_prefix: str = "proposal-history",
) -> S3ManifestRow:
    """Create one schema-validated S3 manifest row for a copied document."""
    return S3ManifestRow(
        document_id=metadata.document_id,
        proposal_id=metadata.proposal_id,
        local_clean_path=str(local_clean_path),
        metadata_path=str(metadata_path),
        recommended_s3_key=build_recommended_s3_key(
            metadata,
            clean_filename=clean_filename,
            base_prefix=base_prefix,
        ),
        include_in_future_rag=metadata.inclusion.include_in_future_rag,
        rag_priority=metadata.inclusion.rag_priority,
    )


def write_s3_manifest(path: Path, rows: Iterable[S3ManifestRow]) -> Path:
    """Write manifest rows as JSONL and return the written path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.model_dump(mode="json"), sort_keys=True))
            handle.write("\n")
    return path
