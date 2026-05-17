"""Tests for clean-set copying and S3 manifest generation."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from proposal_ingest.clean_set_builder import CleanSetBlockedError, build_clean_set
from proposal_ingest.metadata_store import MetadataStore
from proposal_ingest.mock_bedrock import analyze_document_mock
from proposal_ingest.scanner import scan_source_root
from proposal_ingest.schemas import (
    DocumentMetadata,
    QuestionForUser,
    QuestionPriority,
    QuestionStatus,
    RagPriority,
)


def test_clean_set_contains_only_included_files(tmp_path: Path) -> None:
    """The clean set should only include files marked for inclusion and cleared review."""
    source_root, output_root, docs = _build_metadata_run(
        tmp_path,
        {
            "Technical Volume.pdf": "include",
            "Old Draft.pdf": "exclude",
            "Sensitive.pdf": "manual",
        },
    )
    assert source_root.exists()
    run_dir = _write_docs(output_root, docs)

    result = build_clean_set(output_root)

    documents_dir = _branch_documents_dir(run_dir)
    copied_names = sorted(path.name for path in documents_dir.glob("*"))
    assert copied_names == ["Technical_Volume.pdf"]
    assert result.copied_count == 1
    assert result.excluded_count == 2


def test_excluded_files_are_reported_not_copied(tmp_path: Path) -> None:
    """Excluded metadata and inventory-only files should be logged instead of copied."""
    _source_root, output_root, docs = _build_metadata_run(
        tmp_path,
        {
            "Technical Volume.pdf": "include",
            "Budget.xlsx": "exclude",
            "Archive.zip": "inventory_only",
        },
    )
    run_dir = _write_docs(output_root, docs)

    result = build_clean_set(output_root)

    documents_dir = _branch_documents_dir(run_dir)
    copied_names = {path.name for path in documents_dir.glob("*")}
    assert copied_names == {"Technical_Volume.pdf"}

    rows = _read_csv(result.excluded_report_path)
    excluded_names = {row["file_name_original"] for row in rows}
    assert excluded_names == {"Budget.xlsx", "Archive.zip"}
    assert any("no_document_metadata" in row["exclusion_reason"] for row in rows)


def test_filenames_are_sanitized(tmp_path: Path) -> None:
    """Copied files should have sanitized output filenames."""
    _source_root, output_root, docs = _build_metadata_run(
        tmp_path,
        {"Technical Volume FINAL.pdf": "include"},
    )
    run_dir = _write_docs(output_root, docs)

    build_clean_set(output_root)

    documents_dir = _branch_documents_dir(run_dir)
    assert (documents_dir / "Technical_Volume_FINAL.pdf").exists()


def test_filename_collisions_are_disambiguated(tmp_path: Path) -> None:
    """Flattened output should preserve both files when sanitized names collide."""
    _source_root, output_root, docs = _build_metadata_run(
        tmp_path,
        {
            "A/My File.pdf": "include",
            "B/My_File.pdf": "include",
        },
    )
    run_dir = _write_docs(output_root, docs)

    build_clean_set(output_root)

    documents_dir = _branch_documents_dir(run_dir)
    copied_names = sorted(path.name for path in documents_dir.glob("*"))
    assert len(copied_names) == 2
    assert copied_names[0] == "My_File.pdf"
    assert copied_names[1].startswith("My_File__")
    assert copied_names[1].endswith(".pdf")


def test_s3_manifest_rows_match_copied_files(tmp_path: Path) -> None:
    """Manifest rows should correspond to the files copied into the clean set."""
    _source_root, output_root, docs = _build_metadata_run(
        tmp_path,
        {
            "Technical Volume.pdf": "include",
            "Old Draft.pdf": "exclude",
        },
    )
    run_dir = _write_docs(output_root, docs)

    result = build_clean_set(output_root)

    manifest_rows = _read_jsonl(result.manifest_path)
    copied_paths = {str(path) for path in _branch_documents_dir(run_dir).glob("*")}
    manifest_paths = {row["local_clean_path"] for row in manifest_rows}
    assert manifest_paths == copied_paths
    assert len(manifest_rows) == result.copied_count == 1
    row = manifest_rows[0]
    assert row["recommended_s3_key"].startswith("proposal-history/2025/")
    assert row["recommended_s3_key"].endswith("/documents/Technical_Volume.pdf")
    assert row["metadata_path"].endswith(f"{row['document_id']}.json")


def test_critical_open_questions_stop_clean_set(tmp_path: Path) -> None:
    """Critical open questions should block clean output unless explicitly allowed."""
    _source_root, output_root, docs = _build_metadata_run(
        tmp_path,
        {"Technical Volume.pdf": "include"},
    )
    metadata = docs[0]
    docs[0] = metadata.model_copy(
        update={
            "questions_for_user": [
                QuestionForUser(
                    question_id="q_model_001",
                    field="include_in_clean_set",
                    question="Should this critical document be included?",
                    priority=QuestionPriority.critical,
                    status=QuestionStatus.open,
                )
            ]
        }
    )
    run_dir = _write_docs(output_root, docs)

    with pytest.raises(CleanSetBlockedError):
        build_clean_set(output_root)

    result = build_clean_set(output_root, allow_critical_open=True)
    assert result.copied_count == 1
    assert (_branch_documents_dir(run_dir) / "Technical_Volume.pdf").exists()


def _build_metadata_run(
    tmp_path: Path,
    files: dict[str, str],
) -> tuple[Path, Path, list[DocumentMetadata]]:
    source_root = tmp_path / "source"
    output_root = tmp_path / "output"
    branch = source_root / "2025" / "Demo Proposal"
    for relative_path, mode in files.items():
        file_path = branch / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(f"{relative_path} {mode}", encoding="utf-8")

    artifacts = scan_source_root(source_root, output_root)
    docs: list[DocumentMetadata] = []
    for record in artifacts.inventory_records:
        mode = files.get(str(Path(record.relative_path).relative_to("2025/Demo Proposal")))
        if mode == "inventory_only":
            continue
        metadata = analyze_document_mock(record, artifacts.run_id)
        if mode == "exclude":
            data = metadata.model_dump(mode="json")
            data["inclusion"] = {
                "include_in_clean_set": False,
                "include_in_future_rag": False,
                "rag_priority": RagPriority.exclude.value,
                "include_reason": None,
                "exclude_reason": "Not selected for clean set.",
                "recommended_chunking_strategy": None,
            }
            metadata = DocumentMetadata.model_validate(data)
        elif mode == "manual":
            data = metadata.model_dump(mode="json")
            data["sensitivity"]["manual_review_required"] = True
            data["sensitivity"]["manual_review_reasons"] = ["test review gate"]
            metadata = DocumentMetadata.model_validate(data)
        docs.append(metadata)
    return source_root, output_root, docs


def _write_docs(output_root: Path, docs: list[DocumentMetadata]) -> Path:
    run_dir = next((output_root / "logs").glob("run_*"))
    store = MetadataStore(run_dir)
    for doc in docs:
        store.write_document_metadata(doc, append_jsonl=False)
    store.write_document_metadata_jsonl(docs)
    return run_dir


def _branch_documents_dir(run_dir: Path) -> Path:
    return next((run_dir / "mirror" / "2025").glob("*/documents"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]
