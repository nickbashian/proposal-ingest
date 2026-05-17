"""JSON and JSONL writers for document, folder, and run metadata."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from proposal_ingest.schemas import (
    BedrockUsageRecord,
    DocumentMetadata,
    FolderMetadata,
    RunManifest,
)


class MetadataStore:
    """Persist metadata artifacts under a single run directory."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = Path(run_dir)
        self.document_metadata_dir = self.run_dir / "document_metadata"
        self.document_by_id_dir = self.document_metadata_dir / "by_document_id"
        self.all_document_metadata_jsonl = (
            self.document_metadata_dir / "all_document_metadata.jsonl"
        )
        self.folder_metadata_dir = self.run_dir / "folder_metadata"
        self.run_manifest_path = self.run_dir / "run_manifest.json"
        self.usage_dir = self.run_dir / "usage"
        self.failures_dir = self.document_metadata_dir / "failures"
        self.raw_responses_dir = self.run_dir / "raw_responses"

    def document_metadata_path(self, document_id: str) -> Path:
        """Return the canonical path for one document's metadata JSON."""
        return self.document_by_id_dir / f"{document_id}.json"

    def iter_document_metadata_paths(self) -> list[Path]:
        """Return all per-document metadata JSON paths in stable name order."""
        if not self.document_by_id_dir.exists():
            return []
        return sorted(self.document_by_id_dir.glob("*.json"), key=lambda path: path.name)

    def document_metadata_ids(self) -> set[str]:
        """Return document IDs already written for this run."""
        return {path.stem for path in self.iter_document_metadata_paths()}

    def load_document_metadata_by_id(self) -> dict[str, DocumentMetadata]:
        """Load all stored document metadata keyed by document_id."""
        result: dict[str, DocumentMetadata] = {}
        for path in self.iter_document_metadata_paths():
            metadata = DocumentMetadata.model_validate_json(path.read_text(encoding="utf-8"))
            result[metadata.document_id] = metadata
        return result

    def write_document_metadata(
        self, metadata: DocumentMetadata, *, append_jsonl: bool = True
    ) -> Path:
        self.document_by_id_dir.mkdir(parents=True, exist_ok=True)
        path = self.document_metadata_path(metadata.document_id)
        self._write_json(path, metadata)
        if append_jsonl:
            self.document_metadata_dir.mkdir(parents=True, exist_ok=True)
            self._append_jsonl(self.all_document_metadata_jsonl, metadata)
        return path

    def write_document_metadata_jsonl(self, documents: Iterable[DocumentMetadata]) -> Path:
        self.document_metadata_dir.mkdir(parents=True, exist_ok=True)
        path = self.all_document_metadata_jsonl
        with path.open("w", encoding="utf-8") as handle:
            for document in documents:
                handle.write(self._dump_line(document))
                handle.write("\n")
        return path

    def write_folder_metadata(self, metadata: FolderMetadata) -> Path:
        self.folder_metadata_dir.mkdir(parents=True, exist_ok=True)
        path = self.folder_metadata_dir / f"{metadata.proposal_id}.json"
        self._write_json(path, metadata)
        return path

    def write_folder_summary(self, proposal_id: str, summary_text: str) -> Path:
        self.folder_metadata_dir.mkdir(parents=True, exist_ok=True)
        path = self.folder_metadata_dir / f"{proposal_id}.md"
        path.write_text(summary_text, encoding="utf-8")
        return path

    def mirror_branch_dir(self, year_folder: str, proposal_branch: str) -> Path:
        return self.run_dir / "mirror" / year_folder / proposal_branch

    def write_mirror_folder_metadata(self, metadata: FolderMetadata) -> Path:
        branch_dir = self.mirror_branch_dir(metadata.year_folder, metadata.proposal_branch)
        branch_dir.mkdir(parents=True, exist_ok=True)
        path = branch_dir / "folder_metadata.json"
        self._write_json(path, metadata)
        return path

    def write_mirror_folder_summary(
        self,
        year_folder: str,
        proposal_branch: str,
        summary_text: str,
    ) -> Path:
        branch_dir = self.mirror_branch_dir(year_folder, proposal_branch)
        branch_dir.mkdir(parents=True, exist_ok=True)
        path = branch_dir / "folder_summary.md"
        path.write_text(summary_text, encoding="utf-8")
        return path

    def write_run_manifest(self, manifest: RunManifest) -> Path:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(self.run_manifest_path, manifest)
        return self.run_manifest_path

    def write_usage_record(self, record: BedrockUsageRecord) -> Path:
        """Append one Bedrock usage record to the run-scoped usage JSONL file."""
        self.usage_dir.mkdir(parents=True, exist_ok=True)
        path = self.usage_dir / "bedrock_usage.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.model_dump(mode="json"), sort_keys=True))
            handle.write("\n")
        return path

    def write_failure_record(self, document_id: str, error_type: str, details: dict) -> Path:
        """Write a JSON failure record for a document whose metadata could not be produced."""
        self.failures_dir.mkdir(parents=True, exist_ok=True)
        path = self.failures_dir / f"{document_id}.json"
        payload = {"document_id": document_id, "error_type": error_type, **details}
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        return path

    def write_raw_response(self, document_id: str, pass_number: int, raw_text: str) -> Path:
        """Save the raw model response text to disk for debugging."""
        self.raw_responses_dir.mkdir(parents=True, exist_ok=True)
        path = self.raw_responses_dir / f"{document_id}_pass{pass_number}.txt"
        path.write_text(raw_text, encoding="utf-8")
        return path

    @staticmethod
    def _append_jsonl(path: Path, model: DocumentMetadata) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(MetadataStore._dump_line(model))
            handle.write("\n")

    @staticmethod
    def _dump_line(model: DocumentMetadata) -> str:
        return json.dumps(model.model_dump(mode="json"), sort_keys=True)

    @staticmethod
    def _write_json(path: Path, model: DocumentMetadata | FolderMetadata | RunManifest) -> None:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(model.model_dump(mode="json"), handle, indent=2, sort_keys=True)
            handle.write("\n")
