"""JSON and JSONL writers for document, folder, and run metadata."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from proposal_ingest.schemas import DocumentMetadata, FolderMetadata, RunManifest


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

	def write_document_metadata(
		self, metadata: DocumentMetadata, *, append_jsonl: bool = True
	) -> Path:
		self.document_by_id_dir.mkdir(parents=True, exist_ok=True)
		path = self.document_by_id_dir / f"{metadata.document_id}.json"
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

	def write_run_manifest(self, manifest: RunManifest) -> Path:
		self.run_dir.mkdir(parents=True, exist_ok=True)
		self._write_json(self.run_manifest_path, manifest)
		return self.run_manifest_path

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
