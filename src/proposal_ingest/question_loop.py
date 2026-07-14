"""Human-review question export and deterministic answer application."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from proposal_ingest.analyzer import find_latest_inventory_jsonl
from proposal_ingest.human_overrides import (
    KNOWLEDGE_BASE_TREATMENT_FIELDS,
    PROPOSAL_FIELD_MAP,
    append_human_override,
    apply_authoritative_document_override,
    apply_knowledge_base_treatment_update,
    canonical_field_key,
    clear_matching_uncertainties,
    coerce_field_value,
    get_value_at_path,
    set_value_at_path,
)
from proposal_ingest.metadata_store import MetadataStore
from proposal_ingest.path_utils import short_hash
from proposal_ingest.schemas import (
    Agency,
    DocumentCategory,
    DocumentMetadata,
    DocumentRole,
    HumanOverrideRecord,
    OriginType,
    Program,
    ProposalMetadata,
    ProposalStatus,
    QuestionPriority,
    QuestionStatus,
    RagPriority,
    RecommendedRagTreatment,
    ReviewQuestion,
    SensitivityLabel,
    UncertaintyScope,
    UnresolvedDecisionType,
    VersionStatus,
)

REVIEW_COLUMNS = [
    "question_id",
    "run_id",
    "proposal_id",
    "proposal_name",
    "scope",
    "decision_type",
    "document_id",
    "affected_document_ids",
    "source_path",
    "proposal_branch",
    "file_name_original",
    "field",
    "question",
    "priority",
    "suggested_options",
    "model_guess",
    "model_confidence",
    "evidence_summary",
    "why_human_input_is_needed",
    "user_answer",
    "answer_type",
    "status",
    "created_at",
    "updated_at",
    "applied_at",
    "notes",
]

ERROR_COLUMNS = [
    "question_id",
    "document_id",
    "field",
    "user_answer",
    "error",
]

_ALLOWED_FIELD_PATHS: dict[str, tuple[str, ...]] = {
    "canonical_proposal_name": ("proposal_context", "canonical_proposal_name"),
    "proposal_short_name": ("proposal_context", "proposal_short_name"),
    "agency": ("proposal_context", "agency"),
    "agency_subunit": ("proposal_context", "agency_subunit"),
    "program": ("proposal_context", "program"),
    "phase": ("proposal_context", "phase"),
    "topic_number": ("proposal_context", "topic_number"),
    "topic_title": ("proposal_context", "topic_title"),
    "solicitation_number": ("proposal_context", "solicitation_number"),
    "status": ("proposal_context", "status"),
    "award_status": ("proposal_context", "award_status"),
    "document_category": ("document_identity", "document_category"),
    "document_role": ("document_identity", "document_role"),
    "origin_type": ("document_identity", "origin_type"),
    "version_status": ("document_identity", "version_status"),
    "include_in_clean_set": ("inclusion", "include_in_clean_set"),
    "include_in_future_rag": ("inclusion", "include_in_future_rag"),
    "rag_priority": ("inclusion", "rag_priority"),
    "recommended_rag_treatment": ("opportunity_treatment", "recommended_rag_treatment"),
    "sensitivity_labels": ("sensitivity", "sensitivity_labels"),
    "manual_review_required": ("sensitivity", "manual_review_required"),
    "manual_review_reasons": ("sensitivity", "manual_review_reasons"),
    "operator_notes": ("operator_notes",),
    "needs_powerpoint_processing": ("needs_powerpoint_processing",),
}

_ENUM_FIELDS: dict[str, type] = {
    "agency": Agency,
    "program": Program,
    "status": ProposalStatus,
    "document_category": DocumentCategory,
    "document_role": DocumentRole,
    "origin_type": OriginType,
    "version_status": VersionStatus,
    "rag_priority": RagPriority,
    "recommended_rag_treatment": RecommendedRagTreatment,
}

_BOOLEAN_FIELDS = {
    "include_in_clean_set",
    "include_in_future_rag",
    "manual_review_required",
    "needs_powerpoint_processing",
}
_LIST_FIELDS = {"sensitivity_labels", "manual_review_reasons"}
_NOTES_ONLY_FIELDS = {"operator_notes"}


@dataclass(frozen=True)
class ExportQuestionsResult:
    """Summary of a questions CSV export."""

    run_dir: Path
    questions_csv: Path
    exported_count: int
    suppressed_count: int


@dataclass(frozen=True)
class ApplyAnswersResult:
    """Summary of deterministic answer application."""

    run_dir: Path
    answers_csv: Path
    applied_count: int
    invalid_count: int
    skipped_count: int
    archive_csv: Path
    errors_csv: Path


def find_latest_run_dir(output_root: Path) -> Path:
    """Return the latest run directory under an output root."""
    inventory_path = find_latest_inventory_jsonl(output_root)
    if inventory_path is None:
        raise FileNotFoundError(f"No run inventory found under {output_root}/logs/.")
    return inventory_path.parent.parent


def export_questions_to_csv(
    output_root: Path,
    *,
    include_low_priority: bool = False,
) -> ExportQuestionsResult:
    """Export review questions: proposal-level arbitration output plus operational questions.

    Proposal-scoped questions come from the ``arbitrate-questions`` stage
    (see ``question_arbiter.py``), which reconciles document-level
    uncertainties into a small, budget-capped set per proposal. Document
    analysis itself no longer feeds this CSV directly; explicitly generated
    operational questions (for example unsupported PowerPoint handling)
    still export unchanged, independent of the arbitration budgets.
    """
    run_dir = find_latest_run_dir(output_root)
    review_dir = Path(output_root) / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    questions_csv = review_dir / "questions_to_answer.csv"

    exported: list[ReviewQuestion] = []
    suppressed = 0
    seen_ids: set[str] = set()

    store = MetadataStore(run_dir)
    for question in store.load_arbitrated_questions():
        if question.priority == QuestionPriority.low and not include_low_priority:
            suppressed += 1
            continue
        if question.question_id in seen_ids:
            continue
        seen_ids.add(question.question_id)
        exported.append(question)

    for question in _powerpoint_questions(run_dir):
        if question.priority == QuestionPriority.low and not include_low_priority:
            suppressed += 1
            continue
        if question.question_id in seen_ids:
            continue
        seen_ids.add(question.question_id)
        exported.append(question)

    exported.sort(key=lambda q: (q.proposal_id, q.file_name_original or "", q.question_id))
    _write_questions_csv(questions_csv, exported)
    return ExportQuestionsResult(run_dir, questions_csv, len(exported), suppressed)


def apply_answers_from_csv(output_root: Path, answers_csv: Path) -> ApplyAnswersResult:
    """Apply answered review CSV rows to JSON metadata without calling a model."""
    output_root = Path(output_root)
    run_dir = find_latest_run_dir(output_root)
    review_dir = output_root / "review"
    reports_dir = run_dir / "reports"
    review_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    archive_csv = review_dir / "answered_questions_archive.csv"
    errors_csv = reports_dir / "answer_apply_errors.csv"

    store = MetadataStore(run_dir)
    metadata_by_id = store.load_document_metadata_by_id()
    proposal_by_id = store.load_proposal_metadata_by_id()
    changed_proposal_ids: set[str] = set()
    archive_rows: list[dict[str, str]] = []
    error_rows: list[dict[str, str]] = []
    applied_count = 0
    skipped_count = 0

    rows = _read_csv_rows(answers_csv)
    now = datetime.now(UTC).isoformat()
    for row in rows:
        answer = (row.get("user_answer") or "").strip()
        status = (row.get("status") or "open").strip().lower()
        field = (row.get("field") or "").strip()
        document_id = row.get("document_id") or ""
        scope = (row.get("scope") or "").strip().lower()

        if not answer or status in {
            QuestionStatus.skipped.value,
            QuestionStatus.applied.value,
            "skip",
        }:
            skipped_count += 1
            continue

        if scope in {UncertaintyScope.proposal.value, UncertaintyScope.document_family.value}:
            try:
                _apply_proposal_scoped_answer(
                    row,
                    answer=answer,
                    proposal_by_id=proposal_by_id,
                    metadata_by_id=metadata_by_id,
                    store=store,
                    output_root=output_root,
                    now=now,
                )
            except (ValueError, ValidationError) as exc:
                error_rows.append(_error_row(row, str(exc)))
                continue
            changed_proposal_ids.add(row.get("proposal_id", ""))
            row["status"] = QuestionStatus.applied.value
            row["applied_at"] = now
            row["updated_at"] = now
            archive_rows.append({column: row.get(column, "") for column in REVIEW_COLUMNS})
            applied_count += 1
            continue

        if not document_id or document_id not in metadata_by_id:
            if field == "needs_powerpoint_processing" and answer:
                try:
                    parsed_answer = _parse_bool(answer)
                except ValueError as exc:
                    error_rows.append(_error_row(row, str(exc)))
                    continue
                _append_powerpoint_override(run_dir, row, parsed_answer, now)
                row["status"] = QuestionStatus.applied.value
                row["applied_at"] = now
                row["updated_at"] = now
                archive_rows.append({column: row.get(column, "") for column in REVIEW_COLUMNS})
                applied_count += 1
                continue
            error_rows.append(_error_row(row, "metadata for document_id was not found"))
            continue
        if field not in _ALLOWED_FIELD_PATHS:
            error_rows.append(_error_row(row, f"field is not allowed: {field}"))
            continue

        metadata = metadata_by_id[document_id]
        data = metadata.model_dump(mode="json")
        try:
            _apply_field(data, field, answer, row.get("answer_type") or None)
            updated = DocumentMetadata.model_validate(data)
        except (ValueError, ValidationError) as exc:
            error_rows.append(_error_row(row, str(exc)))
            continue

        metadata_by_id[document_id] = updated
        metadata_path = store.document_metadata_path(document_id)
        metadata_path.write_text(
            json.dumps(updated.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        row["status"] = QuestionStatus.applied.value
        row["applied_at"] = now
        row["updated_at"] = now
        row.setdefault("notes", "")
        archive_rows.append({column: row.get(column, "") for column in REVIEW_COLUMNS})
        applied_count += 1

    if archive_rows:
        _append_csv(archive_csv, REVIEW_COLUMNS, archive_rows)
    _write_csv(errors_csv, ERROR_COLUMNS, error_rows)
    _rewrite_all_document_metadata_jsonl(store, metadata_by_id.values())
    if changed_proposal_ids:
        for proposal_id in changed_proposal_ids:
            store.write_proposal_metadata(proposal_by_id[proposal_id])
        store.write_proposal_metadata_jsonl(proposal_by_id.values())

    return ApplyAnswersResult(
        run_dir=run_dir,
        answers_csv=answers_csv,
        applied_count=applied_count,
        invalid_count=len(error_rows),
        skipped_count=skipped_count,
        archive_csv=archive_csv,
        errors_csv=errors_csv,
    )


def stable_question_id(document_id: str, field: str | None, question: str) -> str:
    """Build a stable review question id from document, field, and normalized text."""
    normalized = " ".join(question.lower().split())
    return f"q_{short_hash(f'{document_id}|{field or ''}|{normalized}', length=12)}"


def _powerpoint_questions(run_dir: Path) -> list[ReviewQuestion]:
    path = run_dir / "inventory" / "powerpoint_review_questions.jsonl"
    if not path.exists():
        return []
    questions: list[ReviewQuestion] = []
    now = datetime.now(UTC).isoformat()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            raw = json.loads(line)
            question_text = raw.get("question_text", "PowerPoint file needs manual review.")
            document_id = raw.get("document_id")
            qid = stable_question_id(
                document_id or raw.get("relative_path", ""),
                "needs_powerpoint_processing",
                question_text,
            )
            questions.append(
                ReviewQuestion(
                    question_id=qid,
                    proposal_id=raw.get("proposal_id", "unknown"),
                    document_id=document_id,
                    source_path=raw.get("source_path"),
                    file_name_original=Path(raw.get("relative_path", "")).name or None,
                    field="needs_powerpoint_processing",
                    question=question_text,
                    priority=QuestionPriority(raw.get("priority", "medium")),
                    suggested_options="true | false",
                    model_guess="unknown",
                    answer_type="boolean",
                    status=QuestionStatus.open,
                    created_at=now,
                )
            )
    return questions


def _write_questions_csv(path: Path, questions: list[ReviewQuestion]) -> None:
    rows = [q.model_dump(mode="json") for q in questions]
    _write_csv(path, REVIEW_COLUMNS, rows)


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _append_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def _apply_proposal_scoped_answer(
    row: dict[str, str],
    *,
    answer: str,
    proposal_by_id: dict[str, ProposalMetadata],
    metadata_by_id: dict[str, DocumentMetadata],
    store: MetadataStore,
    output_root: Path,
    now: str,
) -> None:
    """Apply one proposal- or document-family-scoped answer and record a durable override.

    Updates the canonical proposal record, propagates to every affected
    document record where the field is carried there too, and appends a
    ``HumanOverrideRecord`` so a future resynthesis (even against a freshly
    analyzed document set) can replay the decision instead of losing it.
    """
    proposal_id = row.get("proposal_id") or ""
    field = (row.get("field") or "").strip()
    decision_type = (row.get("decision_type") or UnresolvedDecisionType.proposal_fact.value).strip()
    question_id = row.get("question_id") or ""
    scope = (row.get("scope") or UncertaintyScope.proposal.value).strip()
    affected_document_ids = [
        doc_id.strip()
        for doc_id in (row.get("affected_document_ids") or "").split("|")
        if doc_id.strip()
    ]

    if not proposal_id or proposal_id not in proposal_by_id:
        raise ValueError("metadata for proposal_id was not found")
    if not field:
        raise ValueError("field is required for proposal-scoped answers")

    proposal_data = proposal_by_id[proposal_id].model_dump(mode="json")

    if decision_type == UnresolvedDecisionType.authoritative_document.value:
        if answer not in affected_document_ids:
            raise ValueError(
                f"Answer must be one of the affected document IDs: {affected_document_ids}"
            )
        previous_value = next(
            (
                entry.get("document_id")
                for entry in proposal_data.get("document_lineage", [])
                if entry.get("is_authoritative")
            ),
            None,
        )
        apply_authoritative_document_override(
            proposal_data,
            chosen_document_id=answer,
            affected_document_ids=affected_document_ids,
        )
        applied_value: Any = answer
        field_key = None
    else:
        field_key = canonical_field_key(field)
        spec = PROPOSAL_FIELD_MAP.get(field_key)
        if spec is None:
            raise ValueError(f"Proposal field is not allowed: {field}")
        applied_value = coerce_field_value(spec, answer)
        previous_value = (
            get_value_at_path(proposal_data, spec.proposal_path) if spec.proposal_path else None
        )
        if spec.proposal_path is not None:
            set_value_at_path(proposal_data, spec.proposal_path, applied_value)
        if field_key in KNOWLEDGE_BASE_TREATMENT_FIELDS:
            apply_knowledge_base_treatment_update(
                proposal_data,
                field_key=field_key,
                value=applied_value,
                affected_document_ids=affected_document_ids,
            )

    proposal_by_id[proposal_id] = ProposalMetadata.model_validate(proposal_data)

    if field_key is not None:
        spec = PROPOSAL_FIELD_MAP[field_key]
        if spec.document_path is not None:
            for document_id in affected_document_ids:
                document = metadata_by_id.get(document_id)
                if document is None:
                    continue
                doc_data = document.model_dump(mode="json")
                set_value_at_path(doc_data, spec.document_path, applied_value)
                clear_matching_uncertainties(doc_data, field)
                updated_document = DocumentMetadata.model_validate(doc_data)
                metadata_by_id[document_id] = updated_document
                store.write_document_metadata(updated_document, append_jsonl=False)

    record = HumanOverrideRecord(
        question_id=question_id,
        scope=UncertaintyScope(scope),
        proposal_id=proposal_id,
        field=field,
        decision_type=UnresolvedDecisionType(decision_type),
        affected_document_ids=affected_document_ids,
        previous_value=previous_value,
        applied_value=applied_value,
        timestamp=now,
        source="human_review",
    )
    append_human_override(output_root, record)


def _apply_field(
    data: dict[str, Any], field: str, raw_answer: str, answer_type: str | None
) -> None:
    path = _ALLOWED_FIELD_PATHS[field]
    value = _coerce_answer(field, raw_answer, answer_type)
    target = data
    for key in path[:-1]:
        next_value = target.setdefault(key, {})
        if not isinstance(next_value, dict):
            raise ValueError(f"Cannot patch through non-object path component: {key}")
        target = next_value
    target[path[-1]] = value


def _coerce_answer(field: str, raw_answer: str, answer_type: str | None) -> Any:
    normalized_type = (answer_type or "").strip().lower()
    if field in _BOOLEAN_FIELDS or normalized_type == "boolean":
        return _parse_bool(raw_answer)
    if field == "sensitivity_labels":
        values = _parse_list(raw_answer)
        valid_values = {item.value for item in SensitivityLabel}
        invalid = [item for item in values if item not in valid_values]
        if invalid:
            raise ValueError(f"Invalid sensitivity label(s): {', '.join(invalid)}")
        return values
    if field in _LIST_FIELDS or normalized_type == "list":
        return _parse_list(raw_answer)
    if field in _ENUM_FIELDS:
        enum_cls = _ENUM_FIELDS[field]
        valid_values = {item.value for item in enum_cls}  # type: ignore[attr-defined]
        if raw_answer not in valid_values:
            raise ValueError(
                f"Invalid {field}: {raw_answer}. Expected one of {sorted(valid_values)}"
            )
        return raw_answer
    if field in _NOTES_ONLY_FIELDS:
        return raw_answer
    return raw_answer


def _parse_bool(raw_answer: str) -> bool:
    normalized = raw_answer.strip().lower()
    if normalized in {"true", "yes", "y", "1"}:
        return True
    if normalized in {"false", "no", "n", "0"}:
        return False
    raise ValueError(f"Invalid boolean answer: {raw_answer}")


def _parse_list(raw_answer: str) -> list[str]:
    if raw_answer.strip().startswith("["):
        loaded = json.loads(raw_answer)
        if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
            raise ValueError("List answers must be a JSON list of strings")
        return loaded
    return [item.strip() for item in raw_answer.replace("|", ",").split(",") if item.strip()]


def _error_row(row: dict[str, str], error: str) -> dict[str, str]:
    return {
        "question_id": row.get("question_id", ""),
        "document_id": row.get("document_id", ""),
        "field": row.get("field", ""),
        "user_answer": row.get("user_answer", ""),
        "error": error,
    }


def _rewrite_all_document_metadata_jsonl(store: MetadataStore, metadata_values: Any) -> None:
    store.write_document_metadata_jsonl(sorted(metadata_values, key=lambda item: item.document_id))


def _append_powerpoint_override(
    run_dir: Path, row: dict[str, str], needs_processing: bool, applied_at: str
) -> None:
    """Persist applied PowerPoint-only answers when no document metadata exists."""
    path = run_dir / "review" / "powerpoint_answer_overrides.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "question_id": row.get("question_id", ""),
        "document_id": row.get("document_id", ""),
        "proposal_id": row.get("proposal_id", ""),
        "source_path": row.get("source_path", ""),
        "field": "needs_powerpoint_processing",
        "needs_powerpoint_processing": needs_processing,
        "applied_at": applied_at,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True))
        handle.write("\n")
