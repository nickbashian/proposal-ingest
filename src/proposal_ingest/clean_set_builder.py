"""Copy selected documents into clean mirrored output folders."""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from proposal_ingest.analyzer import load_inventory_jsonl
from proposal_ingest.human_overrides import load_human_overrides
from proposal_ingest.metadata_store import MetadataStore
from proposal_ingest.path_utils import sanitize_filename
from proposal_ingest.question_loop import stable_question_id
from proposal_ingest.retrieval_builder import (
    build_document_manifest_rows,
    build_proposal_provenance_report,
    build_proposal_retrieval_record,
    build_run_provenance_report,
)
from proposal_ingest.s3_manifest import (
    build_proposal_lineage_index,
    build_proposal_manifest_row,
    build_s3_manifest_row,
    write_s3_manifest,
)
from proposal_ingest.schemas import (
    DocumentMetadata,
    FolderMetadata,
    InventoryRecord,
    ProposalMetadata,
    QuestionPriority,
    QuestionStatus,
    S3ManifestRow,
    UncertaintyImpact,
)

EXCLUDED_FILES_COLUMNS = [
    "document_id",
    "proposal_id",
    "source_path",
    "relative_path",
    "year_folder",
    "proposal_branch",
    "file_name_original",
    "include_in_clean_set",
    "include_in_future_rag",
    "rag_priority",
    "manual_review_required",
    "exclusion_reason",
    "copied",
    "local_clean_path",
]


@dataclass(frozen=True)
class CopiedDocument:
    """One document selected and copied into the clean set."""

    document_id: str
    proposal_id: str
    source_path: Path
    local_clean_path: Path
    metadata_path: Path
    clean_filename: str


@dataclass(frozen=True)
class CleanSetBuildResult:
    """Summary of a clean-set build."""

    run_dir: Path
    copied_documents: list[CopiedDocument]
    excluded_rows: list[dict[str, Any]]
    excluded_report_path: Path
    manifest_path: Path
    manifest_rows: list[S3ManifestRow]
    dry_run: bool = False
    proposal_retrieval_paths: dict[str, Path] = field(default_factory=dict)
    quality_report_path: Path | None = None

    @property
    def copied_count(self) -> int:
        return len(self.copied_documents)

    @property
    def excluded_count(self) -> int:
        return len(self.excluded_rows)

    @property
    def manifest_count(self) -> int:
        return len(self.manifest_rows)

    @property
    def proposal_record_count(self) -> int:
        return len(self.proposal_retrieval_paths)


class CleanSetBlockedError(RuntimeError):
    """Raised when critical open questions block clean-set output."""

    def __init__(self, questions: list[dict[str, str]]) -> None:
        self.questions = questions
        count = len(questions)
        super().__init__(
            f"Clean-set build stopped because {count} critical question(s) remain open."
        )


def build_clean_set(
    output_root: Path,
    *,
    allow_critical_open: bool = False,
    dry_run: bool = False,
    force: bool = False,
    sanitize_filenames: bool = True,
    flatten_documents_folder: bool = True,
    require_manual_review_clearance: bool = True,
    s3_manifest_enabled: bool = True,
    s3_base_prefix: str = "proposal-history",
) -> CleanSetBuildResult:
    """Build clean document copies, metadata copies, reports, and S3 manifest.

    The clean set is rebuilt inside the latest run directory under
    ``output_root/logs``. Source files are only read; all generated artifacts
    are written under the run-scoped output directory.
    """
    output_root = Path(output_root).resolve()
    run_dir = _find_latest_run_dir(output_root)
    store = MetadataStore(run_dir)
    documents_by_id = store.load_document_metadata_by_id()
    documents = sorted(documents_by_id.values(), key=_document_sort_key)
    inventory_records = _load_inventory(run_dir)
    proposals_by_id = store.load_proposal_metadata_by_id()
    docs_by_proposal: dict[str, list[DocumentMetadata]] = {}
    for metadata in documents:
        docs_by_proposal.setdefault(metadata.proposal_id, []).append(metadata)
    # Pre-indexed once per proposal so building a manifest row per document
    # stays O(1) per lookup instead of re-scanning each proposal's lineage.
    lineage_index_by_proposal = {
        proposal_id: build_proposal_lineage_index(proposal)
        for proposal_id, proposal in proposals_by_id.items()
    }

    open_critical = _find_open_critical_questions(output_root, documents, store)
    if open_critical and not allow_critical_open:
        raise CleanSetBlockedError(open_critical)

    plans, excluded_rows = _plan_clean_set(
        store,
        documents,
        inventory_records,
        sanitize_filenames=sanitize_filenames,
        flatten_documents_folder=flatten_documents_folder,
        require_manual_review_clearance=require_manual_review_clearance,
    )

    excluded_report_path = run_dir / "reports" / "excluded_files.csv"
    manifest_path = run_dir / "manifests" / "s3_manifest.jsonl"
    quality_report_path: Path | None = run_dir / "reports" / "quality_report.json"
    manifest_rows: list[S3ManifestRow] = []
    proposal_retrieval_paths: dict[str, Path] = {}

    if not dry_run:
        _prepare_branch_clean_dirs(store, documents, force=force)
        _mirror_folder_outputs(store)
        copied_documents: list[CopiedDocument] = []
        local_clean_paths_by_proposal: dict[str, dict[str, str]] = {}
        metadata_paths_by_proposal: dict[str, dict[str, str]] = {}
        for metadata, clean_path, metadata_path, clean_filename in plans:
            source_path = Path(metadata.system.source_path)
            clean_path.parent.mkdir(parents=True, exist_ok=True)
            metadata_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, clean_path)
            _write_metadata_copy(metadata_path, metadata)
            copied = CopiedDocument(
                document_id=metadata.document_id,
                proposal_id=metadata.proposal_id,
                source_path=source_path,
                local_clean_path=clean_path,
                metadata_path=metadata_path,
                clean_filename=clean_filename,
            )
            copied_documents.append(copied)
            local_clean_paths_by_proposal.setdefault(metadata.proposal_id, {})[
                metadata.document_id
            ] = str(clean_path)
            metadata_paths_by_proposal.setdefault(metadata.proposal_id, {})[
                metadata.document_id
            ] = str(metadata_path)
            if s3_manifest_enabled:
                lineage_by_id, treatment_by_id = lineage_index_by_proposal.get(
                    metadata.proposal_id, (None, None)
                )
                manifest_rows.append(
                    build_s3_manifest_row(
                        metadata,
                        local_clean_path=clean_path,
                        metadata_path=metadata_path,
                        clean_filename=clean_filename,
                        base_prefix=s3_base_prefix,
                        lineage_by_id=lineage_by_id,
                        treatment_by_id=treatment_by_id,
                    )
                )

        _write_excluded_report(excluded_report_path, excluded_rows)

        overrides_by_proposal: dict[str, list[Any]] = {}
        for override in load_human_overrides(output_root):
            overrides_by_proposal.setdefault(override.proposal_id, []).append(override)

        for proposal_id, proposal in sorted(proposals_by_id.items()):
            proposal_docs = docs_by_proposal.get(proposal_id)
            if not proposal_docs:
                continue
            retrieval_path, proposal_metadata_path = _write_proposal_retrieval_artifacts(
                store,
                proposal,
                proposal_docs,
                local_clean_paths=local_clean_paths_by_proposal.get(proposal_id, {}),
                metadata_paths=metadata_paths_by_proposal.get(proposal_id, {}),
                overrides=overrides_by_proposal.get(proposal_id, []),
            )
            proposal_retrieval_paths[proposal_id] = retrieval_path
            if s3_manifest_enabled:
                manifest_rows.append(
                    build_proposal_manifest_row(
                        proposal,
                        retrieval_path=retrieval_path,
                        metadata_path=proposal_metadata_path,
                        base_prefix=s3_base_prefix,
                    )
                )

        write_s3_manifest(manifest_path, manifest_rows)
        assert quality_report_path is not None
        _write_run_quality_report(store, quality_report_path, proposals_by_id)
    else:
        copied_documents = [
            CopiedDocument(
                document_id=metadata.document_id,
                proposal_id=metadata.proposal_id,
                source_path=Path(metadata.system.source_path),
                local_clean_path=clean_path,
                metadata_path=metadata_path,
                clean_filename=clean_filename,
            )
            for metadata, clean_path, metadata_path, clean_filename in plans
        ]
        if s3_manifest_enabled:
            manifest_rows = []
            for metadata, clean_path, metadata_path, clean_filename in plans:
                lineage_by_id, treatment_by_id = lineage_index_by_proposal.get(
                    metadata.proposal_id, (None, None)
                )
                manifest_rows.append(
                    build_s3_manifest_row(
                        metadata,
                        local_clean_path=clean_path,
                        metadata_path=metadata_path,
                        clean_filename=clean_filename,
                        base_prefix=s3_base_prefix,
                        lineage_by_id=lineage_by_id,
                        treatment_by_id=treatment_by_id,
                    )
                )
            for proposal_id, proposal in sorted(proposals_by_id.items()):
                if proposal_id not in docs_by_proposal:
                    continue
                branch_dir = store.mirror_branch_dir(proposal.year_folder, proposal.proposal_branch)
                retrieval_path = branch_dir / "retrieval" / "proposal_context.json"
                proposal_metadata_path = branch_dir / "proposal_metadata.json"
                proposal_retrieval_paths[proposal_id] = retrieval_path
                manifest_rows.append(
                    build_proposal_manifest_row(
                        proposal,
                        retrieval_path=retrieval_path,
                        metadata_path=proposal_metadata_path,
                        base_prefix=s3_base_prefix,
                    )
                )
        quality_report_path = None

    return CleanSetBuildResult(
        run_dir=run_dir,
        copied_documents=copied_documents,
        excluded_rows=excluded_rows,
        excluded_report_path=excluded_report_path,
        manifest_path=manifest_path,
        manifest_rows=manifest_rows,
        dry_run=dry_run,
        proposal_retrieval_paths=proposal_retrieval_paths,
        quality_report_path=quality_report_path,
    )


def _find_latest_run_dir(output_root: Path) -> Path:
    logs_dir = Path(output_root) / "logs"
    if not logs_dir.is_dir():
        raise FileNotFoundError(f"No run directories found under {logs_dir}.")
    run_dirs = sorted(path for path in logs_dir.glob("run_*") if path.is_dir())
    if not run_dirs:
        raise FileNotFoundError(f"No run directories found under {logs_dir}.")
    return run_dirs[-1]


def _load_inventory(run_dir: Path) -> list[InventoryRecord]:
    inventory_path = run_dir / "inventory" / "file_inventory.jsonl"
    if not inventory_path.exists():
        return []
    return load_inventory_jsonl(inventory_path)


def _plan_clean_set(
    store: MetadataStore,
    documents: list[DocumentMetadata],
    inventory_records: list[InventoryRecord],
    *,
    sanitize_filenames: bool,
    flatten_documents_folder: bool,
    require_manual_review_clearance: bool,
) -> tuple[list[tuple[DocumentMetadata, Path, Path, str]], list[dict[str, Any]]]:
    plans: list[tuple[DocumentMetadata, Path, Path, str]] = []
    excluded_rows: list[dict[str, Any]] = []
    used_paths: set[Path] = set()
    documents_by_id = {document.document_id: document for document in documents}

    for metadata in documents:
        exclusion_reason = _document_exclusion_reason(
            metadata,
            require_manual_review_clearance=require_manual_review_clearance,
        )
        source_path = Path(metadata.system.source_path)
        if exclusion_reason is None and not source_path.is_file():
            exclusion_reason = "source_file_missing"

        if exclusion_reason is not None:
            excluded_rows.append(_excluded_row_from_metadata(metadata, exclusion_reason))
            continue

        clean_filename = _clean_filename(metadata, sanitize_filenames=sanitize_filenames)
        branch_dir = store.mirror_branch_dir(
            metadata.system.year_folder,
            metadata.system.proposal_branch,
        )
        target_dir = _target_documents_dir(
            branch_dir,
            metadata,
            flatten_documents_folder=flatten_documents_folder,
        )
        clean_path = _resolve_collision(
            target_dir / clean_filename,
            metadata=metadata,
            used_paths=used_paths,
        )
        clean_filename = clean_path.name
        metadata_path = branch_dir / "metadata" / f"{metadata.document_id}.json"
        used_paths.add(clean_path)
        plans.append((metadata, clean_path, metadata_path, clean_filename))

    for record in inventory_records:
        if record.document_id in documents_by_id:
            continue
        excluded_rows.append(_excluded_row_from_inventory(record, "no_document_metadata"))

    excluded_rows.sort(
        key=lambda row: (
            str(row.get("proposal_id") or ""),
            str(row.get("relative_path") or ""),
            str(row.get("document_id") or ""),
        )
    )
    return plans, excluded_rows


def _document_exclusion_reason(
    metadata: DocumentMetadata,
    *,
    require_manual_review_clearance: bool,
) -> str | None:
    if not metadata.inclusion.include_in_clean_set:
        return metadata.inclusion.exclude_reason or "include_in_clean_set_false"
    if require_manual_review_clearance and metadata.sensitivity.manual_review_required:
        reasons = metadata.sensitivity.manual_review_reasons
        if reasons:
            return f"manual_review_required: {'; '.join(reasons)}"
        return "manual_review_required"
    return None


def _clean_filename(metadata: DocumentMetadata, *, sanitize_filenames: bool) -> str:
    source_name = metadata.system.file_name_original
    if sanitize_filenames:
        return sanitize_filename(source_name)
    return source_name


def _target_documents_dir(
    branch_dir: Path,
    metadata: DocumentMetadata,
    *,
    flatten_documents_folder: bool,
) -> Path:
    documents_dir = branch_dir / "documents"
    if flatten_documents_folder:
        return documents_dir

    relative_parent = Path(metadata.system.relative_path).parent
    if str(relative_parent) in {"", "."}:
        return documents_dir
    safe_parts = [sanitize_filename(part) for part in relative_parent.parts]
    target = documents_dir
    for part in safe_parts:
        target = target / part
    return target


def _resolve_collision(
    target_path: Path,
    *,
    metadata: DocumentMetadata,
    used_paths: set[Path],
) -> Path:
    if target_path not in used_paths:
        return target_path

    suffix = target_path.suffix
    stem = target_path.stem
    discriminator = metadata.system.sha256[:8] or metadata.document_id[-8:]
    candidate = target_path.with_name(f"{stem}__{discriminator}{suffix}")
    counter = 2
    while candidate in used_paths:
        candidate = target_path.with_name(f"{stem}__{discriminator}_{counter}{suffix}")
        counter += 1
    return candidate


def _prepare_branch_clean_dirs(
    store: MetadataStore,
    documents: list[DocumentMetadata],
    *,
    force: bool,
) -> None:
    del force  # Rebuilding generated clean-set directories is deterministic.
    branch_keys = {
        (document.system.year_folder, document.system.proposal_branch) for document in documents
    }
    for year_folder, proposal_branch in branch_keys:
        branch_dir = store.mirror_branch_dir(year_folder, proposal_branch)
        for child in (branch_dir / "documents", branch_dir / "metadata"):
            if child.exists():
                shutil.rmtree(child)
            child.mkdir(parents=True, exist_ok=True)


def _mirror_folder_outputs(store: MetadataStore) -> None:
    if not store.folder_metadata_dir.exists():
        return
    for metadata_path in sorted(store.folder_metadata_dir.glob("*.json")):
        metadata = FolderMetadata.model_validate_json(metadata_path.read_text(encoding="utf-8"))
        store.write_mirror_folder_metadata(metadata)
        summary_path = store.folder_metadata_dir / f"{metadata.proposal_id}.md"
        if summary_path.exists():
            store.write_mirror_folder_summary(
                metadata.year_folder,
                metadata.proposal_branch,
                summary_path.read_text(encoding="utf-8"),
            )


def _write_metadata_copy(path: Path, metadata: DocumentMetadata) -> None:
    path.write_text(
        json.dumps(metadata.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_json_dict(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_proposal_retrieval_artifacts(
    store: MetadataStore,
    proposal: ProposalMetadata,
    proposal_docs: list[DocumentMetadata],
    *,
    local_clean_paths: dict[str, str],
    metadata_paths: dict[str, str],
    overrides: list[Any],
) -> tuple[Path, Path]:
    """Write one proposal's first-class RAG retrieval object and provenance report.

    Returns ``(retrieval_path, proposal_metadata_path)`` so the caller can
    reference them from the S3/RAG manifest's proposal-record row.
    """
    branch_dir = store.mirror_branch_dir(proposal.year_folder, proposal.proposal_branch)
    retrieval_dir = branch_dir / "retrieval"

    retrieval_record = build_proposal_retrieval_record(proposal, proposal_docs)
    retrieval_path = retrieval_dir / "proposal_context.json"
    _write_json_dict(retrieval_path, retrieval_record.model_dump(mode="json"))

    manifest_entries = build_document_manifest_rows(
        proposal,
        proposal_docs,
        local_clean_paths=local_clean_paths,
        metadata_paths=metadata_paths,
    )
    document_manifest_path = retrieval_dir / "document_manifest.jsonl"
    document_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with document_manifest_path.open("w", encoding="utf-8") as handle:
        for entry in manifest_entries:
            handle.write(json.dumps(entry.model_dump(mode="json"), sort_keys=True))
            handle.write("\n")

    proposal_metadata_path = branch_dir / "proposal_metadata.json"
    _write_json_dict(proposal_metadata_path, proposal.model_dump(mode="json"))

    provenance_report = build_proposal_provenance_report(
        proposal, proposal_docs, overrides=overrides
    )
    _write_json_dict(branch_dir / "provenance_report.json", provenance_report)

    return retrieval_path, proposal_metadata_path


def _write_run_quality_report(
    store: MetadataStore,
    quality_report_path: Path,
    proposals_by_id: dict[str, ProposalMetadata],
) -> None:
    arbitration_summary = store.load_arbitration_summary()
    report = build_run_provenance_report(
        list(proposals_by_id.values()),
        arbitrated_questions=store.load_arbitrated_questions(),
        suppressed_count=arbitration_summary.get("suppressed_count", 0),
        resolved_by_override_count=arbitration_summary.get("resolved_by_override_count", 0),
        usage_records=store.load_usage_records(),
    )
    _write_json_dict(quality_report_path, report)


def _write_excluded_report(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXCLUDED_FILES_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _excluded_row_from_metadata(metadata: DocumentMetadata, reason: str) -> dict[str, Any]:
    return {
        "document_id": metadata.document_id,
        "proposal_id": metadata.proposal_id,
        "source_path": metadata.system.source_path,
        "relative_path": metadata.system.relative_path,
        "year_folder": metadata.system.year_folder,
        "proposal_branch": metadata.system.proposal_branch,
        "file_name_original": metadata.system.file_name_original,
        "include_in_clean_set": metadata.inclusion.include_in_clean_set,
        "include_in_future_rag": metadata.inclusion.include_in_future_rag,
        "rag_priority": metadata.inclusion.rag_priority,
        "manual_review_required": metadata.sensitivity.manual_review_required,
        "exclusion_reason": reason,
        "copied": False,
        "local_clean_path": "",
    }


def _excluded_row_from_inventory(record: InventoryRecord, reason: str) -> dict[str, Any]:
    detail = record.skip_reason or str(record.processing_status)
    return {
        "document_id": record.document_id,
        "proposal_id": record.proposal_id,
        "source_path": record.source_path,
        "relative_path": record.relative_path,
        "year_folder": record.year_folder,
        "proposal_branch": record.proposal_branch,
        "file_name_original": record.file_name_original,
        "include_in_clean_set": False,
        "include_in_future_rag": False,
        "rag_priority": "exclude",
        "manual_review_required": "",
        "exclusion_reason": f"{reason}: {detail}",
        "copied": False,
        "local_clean_path": "",
    }


def _find_open_critical_questions(
    output_root: Path,
    documents: list[DocumentMetadata],
    store: MetadataStore,
) -> list[dict[str, str]]:
    applied_question_ids = _load_applied_question_ids(Path(output_root))
    review_rows = _load_review_rows(Path(output_root))
    review_by_id = {row.get("question_id", ""): row for row in review_rows}
    blocked: dict[str, dict[str, str]] = {}

    for metadata in documents:
        for question in metadata.questions_for_user:
            if question.priority != QuestionPriority.critical:
                continue
            if question.status != QuestionStatus.open:
                continue
            question_id = stable_question_id(
                metadata.document_id,
                question.field,
                question.question,
            )
            if question_id in applied_question_ids:
                continue
            review_row = review_by_id.get(question_id)
            if review_row and _review_row_resolved(review_row):
                continue
            blocked[question_id] = {
                "question_id": question_id,
                "document_id": metadata.document_id,
                "proposal_id": metadata.proposal_id,
                "field": question.field or "",
                "question": question.question,
            }

        for uncertainty in metadata.uncertainties:
            if uncertainty.downstream_impact != UncertaintyImpact.critical:
                continue
            question_id = stable_question_id(
                metadata.document_id,
                uncertainty.field,
                uncertainty.reason_unresolved,
            )
            if question_id in applied_question_ids:
                continue
            review_row = review_by_id.get(question_id)
            if review_row and _review_row_resolved(review_row):
                continue
            blocked[question_id] = {
                "question_id": question_id,
                "document_id": metadata.document_id,
                "proposal_id": metadata.proposal_id,
                "field": uncertainty.field,
                "question": uncertainty.reason_unresolved,
            }

    for row in review_rows:
        question_id = row.get("question_id", "")
        if question_id in blocked or question_id in applied_question_ids:
            continue
        if (row.get("priority") or "").strip().lower() != QuestionPriority.critical.value:
            continue
        if _review_row_resolved(row):
            continue
        blocked[question_id] = {
            "question_id": question_id,
            "document_id": row.get("document_id", ""),
            "proposal_id": row.get("proposal_id", ""),
            "field": row.get("field", ""),
            "question": row.get("question", ""),
        }

    # Belt-and-suspenders: also consult this run's arbitration output directly
    # (via the durable human-override log, independent of whether
    # export-questions has been rerun since arbitrate-questions), so a
    # critical proposal-level question can never slip through the gate
    # merely because the CSV export step was skipped or is stale.
    overridden_question_ids = {o.question_id for o in load_human_overrides(Path(output_root))}
    for arbitrated_question in store.load_arbitrated_questions():
        if arbitrated_question.priority != QuestionPriority.critical:
            continue
        if (
            arbitrated_question.question_id in blocked
            or arbitrated_question.question_id in overridden_question_ids
        ):
            continue
        blocked[arbitrated_question.question_id] = {
            "question_id": arbitrated_question.question_id,
            "document_id": arbitrated_question.document_id or "",
            "proposal_id": arbitrated_question.proposal_id,
            "field": arbitrated_question.field or "",
            "question": arbitrated_question.question,
        }

    return sorted(blocked.values(), key=lambda row: row["question_id"])


def _review_row_resolved(row: dict[str, str]) -> bool:
    status = (row.get("status") or "").strip().lower()
    return status in {
        QuestionStatus.applied.value,
        QuestionStatus.suppressed.value,
        QuestionStatus.skipped.value,
        "skip",
    }


def _load_applied_question_ids(output_root: Path) -> set[str]:
    archive_path = output_root / "review" / "answered_questions_archive.csv"
    if not archive_path.exists():
        return set()
    applied: set[str] = set()
    with archive_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if (row.get("status") or "").strip().lower() == QuestionStatus.applied.value:
                question_id = row.get("question_id")
                if question_id:
                    applied.add(question_id)
    return applied


def _load_review_rows(output_root: Path) -> list[dict[str, str]]:
    questions_path = output_root / "review" / "questions_to_answer.csv"
    if not questions_path.exists():
        return []
    with questions_path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _document_sort_key(metadata: DocumentMetadata) -> tuple[str, str, str, str]:
    return (
        metadata.system.year_folder,
        metadata.system.proposal_branch.lower(),
        metadata.system.relative_path.lower(),
        metadata.document_id,
    )
