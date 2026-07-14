"""Generate the local S3/RAG manifest JSONL for future ingestion.

Manifest rows are typed by ``object_type``: one ``proposal_record`` row per
proposal (the primary retrieval entry point, pointing at
``retrieval/proposal_context.json``) plus one ``document`` row per copied
document, carrying the lineage/treatment relationship fields a downstream
retrieval client needs to go from a proposal overview to its authoritative
or supporting documents (issue #9).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from proposal_ingest.schemas import (
    DocumentLineageEntry,
    DocumentMetadata,
    KnowledgeBaseTreatment,
    ManifestObjectType,
    ProposalMetadata,
    RagPriority,
    S3ManifestRow,
)


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


def build_proposal_record_s3_key(
    *,
    year_folder: str,
    proposal_id: str,
    base_prefix: str = "proposal-history",
) -> str:
    """Return the future S3 key for a proposal's retrieval entry point."""
    parts = [base_prefix.strip("/"), year_folder, proposal_id, "retrieval", "proposal_context.json"]
    return "/".join(part.strip("/") for part in parts if part.strip("/"))


def build_s3_manifest_row(
    metadata: DocumentMetadata,
    *,
    local_clean_path: Path,
    metadata_path: Path,
    clean_filename: str,
    base_prefix: str = "proposal-history",
    proposal: ProposalMetadata | None = None,
) -> S3ManifestRow:
    """Create one schema-validated S3/RAG manifest row for a copied document.

    When ``proposal`` (the copied document's synthesized proposal record) is
    supplied, the row is enriched with lineage and knowledge-base-treatment
    relationship fields; without it, only the fields document-level metadata
    can supply on its own are populated.
    """
    lineage: DocumentLineageEntry | None = None
    treatment: KnowledgeBaseTreatment | None = None
    if proposal is not None:
        lineage = next(
            (e for e in proposal.document_lineage if e.document_id == metadata.document_id),
            None,
        )
        treatment = next(
            (t for t in proposal.knowledge_base_treatment if t.document_id == metadata.document_id),
            None,
        )

    return S3ManifestRow(
        object_type=ManifestObjectType.document,
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
        document_role=(
            lineage.document_role if lineage else metadata.document_identity.document_role
        ),
        version_status=(
            lineage.version_status if lineage else metadata.document_identity.version_status
        ),
        authority_rank=lineage.authority_rank if lineage else None,
        recommended_rag_treatment=treatment.recommended_rag_treatment if treatment else None,
        is_authoritative=lineage.is_authoritative if lineage else None,
        superseded_by_document_id=lineage.superseded_by_document_id if lineage else None,
        contains_unique_reasoning=lineage.contains_unique_reasoning if lineage else None,
        sensitivity_labels=metadata.sensitivity.sensitivity_labels,
        parent_proposal_record=metadata.proposal_id if proposal is not None else None,
    )


def build_proposal_manifest_row(
    proposal: ProposalMetadata,
    *,
    retrieval_path: Path,
    metadata_path: Path,
    base_prefix: str = "proposal-history",
) -> S3ManifestRow:
    """Create the ``proposal_record`` manifest row: a proposal's retrieval entry point."""
    return S3ManifestRow(
        object_type=ManifestObjectType.proposal_record,
        document_id=None,
        proposal_id=proposal.proposal_id,
        local_clean_path=str(retrieval_path),
        metadata_path=str(metadata_path),
        recommended_s3_key=build_proposal_record_s3_key(
            year_folder=proposal.year_folder,
            proposal_id=proposal.proposal_id,
            base_prefix=base_prefix,
        ),
        include_in_future_rag=True,
        rag_priority=RagPriority.high,
        parent_proposal_record=None,
    )


def write_s3_manifest(path: Path, rows: Iterable[S3ManifestRow]) -> Path:
    """Write manifest rows as JSONL and return the written path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.model_dump(mode="json"), sort_keys=True))
            handle.write("\n")
    return path
