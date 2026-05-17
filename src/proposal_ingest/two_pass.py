"""Phase 9 two-pass contextual review for low-confidence document metadata."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from proposal_ingest.bedrock_client import call_converse_with_text, create_bedrock_runtime_client
from proposal_ingest.config import RuntimeConfig
from proposal_ingest.extractors import extract_text
from proposal_ingest.logging_utils import get_logger
from proposal_ingest.metadata_store import MetadataStore
from proposal_ingest.model_output import normalize_metadata_output
from proposal_ingest.prompts import load_pass2_system_prompt, render_pass2_user_prompt
from proposal_ingest.schemas import (
    APP_SCHEMA_VERSION,
    BedrockUsageRecord,
    DocumentCategory,
    DocumentMetadata,
    DocumentRole,
    OriginType,
    ProcessingStatus,
)

logger = get_logger("two_pass")

_MERGE_FIELD_SPECS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("document_identity", "document_category"), ("confidence", "document_category")),
    (("document_identity", "document_role"), ("confidence", "document_role")),
    (("document_identity", "origin_type"), ("confidence", "origin_type")),
    (("document_identity", "version_status"), ("confidence", "version_status")),
    (("proposal_context", "canonical_proposal_name"), ("confidence", "canonical_proposal_name")),
    (("proposal_context", "agency"), ("confidence", "agency")),
    (("proposal_context", "program"), ("confidence", "program")),
    (("proposal_context", "status"), ("confidence", "status")),
    (("proposal_context", "award_status"), ("confidence", "award_status")),
    (("inclusion", "include_in_clean_set"), ("confidence", "include_in_clean_set")),
    (("inclusion", "include_in_future_rag"), ("confidence", "include_in_future_rag")),
    (("inclusion", "rag_priority"), ("confidence", "rag_priority")),
)


@dataclass(frozen=True)
class Pass2RunResult:
    """Summary of contextual review for one analyze run."""

    documents_by_id: dict[str, DocumentMetadata]
    reviewed_count: int
    changed_count: int
    report_path: Path


def run_two_pass_review(
    run_dir: Path,
    run_id: str,
    config: RuntimeConfig,
    *,
    use_mock: bool,
) -> Pass2RunResult:
    """Review flagged low-confidence documents with proposal-branch context."""
    store = MetadataStore(run_dir)
    metadata_by_id = store.load_document_metadata_by_id()
    threshold = config.processing.pass2_confidence_threshold
    flagged_docs = [
        metadata
        for metadata in metadata_by_id.values()
        if _needs_context_pass2(metadata, threshold)
    ]
    report_path = run_dir / "reports" / "pass2_changes.csv"
    report_rows: list[dict[str, str]] = []

    for metadata in flagged_docs:
        flagged_metadata = metadata.model_copy(deep=True)
        flagged_metadata.system.processing_status = ProcessingStatus.needs_context_pass2
        store.write_document_metadata(flagged_metadata, append_jsonl=False)

        context_packet = build_branch_context_packet(
            flagged_metadata,
            metadata_by_id.values(),
            threshold=threshold,
        )
        pass2_candidate, usage_record, error_message = _review_document_with_pass2(
            flagged_metadata,
            context_packet,
            run_id,
            config,
            use_mock=use_mock,
        )
        if usage_record is not None:
            store.write_usage_record(usage_record)

        if pass2_candidate is None:
            failed_metadata = flagged_metadata.model_copy(deep=True)
            failed_metadata.processing_notes.append(
                f"pass2_failed: {error_message or 'unknown error'}"
            )
            store.write_document_metadata(failed_metadata, append_jsonl=False)
            metadata_by_id[failed_metadata.document_id] = failed_metadata
            store.write_failure_record(
                failed_metadata.document_id,
                "pass2_failed",
                {
                    "error_message": error_message or "unknown error",
                    "source_path": failed_metadata.system.source_path,
                },
            )
            continue

        merged_metadata, changes = _merge_pass2_candidate(
            flagged_metadata,
            pass2_candidate,
            threshold=threshold,
        )
        merged_metadata.processing_notes.append("pass2_review_completed")
        store.write_document_metadata(merged_metadata, append_jsonl=False)
        metadata_by_id[merged_metadata.document_id] = merged_metadata
        for change in changes:
            report_rows.append(change)

    _write_pass2_report(report_path, report_rows)
    return Pass2RunResult(
        documents_by_id=metadata_by_id,
        reviewed_count=len(flagged_docs),
        changed_count=len(report_rows),
        report_path=report_path,
    )


def build_branch_context_packet(
    target: DocumentMetadata,
    branch_documents: list[DocumentMetadata] | Any,
    *,
    threshold: float,
) -> dict[str, Any]:
    """Assemble the branch context used for contextual re-analysis."""
    same_branch = [
        metadata
        for metadata in branch_documents
        if metadata.proposal_id == target.proposal_id and metadata.document_id != target.document_id
    ]
    high_conf_docs = [
        {
            "document_id": metadata.document_id,
            "file_name_original": metadata.system.file_name_original,
            "document_category": metadata.document_identity.document_category,
            "document_role": metadata.document_identity.document_role,
            "summary_short": metadata.content.summary_short,
            "canonical_proposal_name": metadata.proposal_context.canonical_proposal_name,
            "agency": metadata.proposal_context.agency,
            "program": metadata.proposal_context.program,
        }
        for metadata in same_branch
        if metadata.confidence.document_category >= threshold
        or metadata.confidence.document_role >= threshold
    ]
    if not high_conf_docs:
        ranked_docs = sorted(
            same_branch,
            key=lambda metadata: max(
                float(metadata.confidence.document_category),
                float(metadata.confidence.document_role),
            ),
            reverse=True,
        )
        high_conf_docs = [
            {
                "document_id": metadata.document_id,
                "file_name_original": metadata.system.file_name_original,
                "document_category": metadata.document_identity.document_category,
                "document_role": metadata.document_identity.document_role,
                "summary_short": metadata.content.summary_short,
                "canonical_proposal_name": metadata.proposal_context.canonical_proposal_name,
                "agency": metadata.proposal_context.agency,
                "program": metadata.proposal_context.program,
            }
            for metadata in ranked_docs[:5]
        ]
    return {
        "branch_context": {
            "year_folder": target.system.year_folder,
            "proposal_branch": target.system.proposal_branch,
            "proposal_branch_note": "Folder name is low-trust context and may be imperfect.",
        },
        "high_confidence_documents": high_conf_docs,
        "preliminary_branch_signals": {
            "canonical_proposal_name": _most_common_known(
                metadata.proposal_context.canonical_proposal_name for metadata in same_branch
            ),
            "agency": _most_common_known(
                metadata.proposal_context.agency for metadata in same_branch
            ),
            "program": _most_common_known(
                metadata.proposal_context.program for metadata in same_branch
            ),
        },
        "tracker_candidates": [],
        "current_pass1_metadata": target.model_dump(mode="json"),
    }


def _needs_context_pass2(metadata: DocumentMetadata, threshold: float) -> bool:
    extra = getattr(metadata, "__pydantic_extra__", {}) or {}
    return any(
        (
            metadata.confidence.document_category < threshold,
            metadata.confidence.document_role < threshold,
            metadata.confidence.include_in_future_rag < threshold,
            metadata.document_identity.origin_type == OriginType.unknown,
            _is_unknown(metadata.proposal_context.canonical_proposal_name),
            bool(extra.get("needs_context_pass2")),
        )
    )


def _review_document_with_pass2(
    metadata: DocumentMetadata,
    context_packet: dict[str, Any],
    run_id: str,
    config: RuntimeConfig,
    *,
    use_mock: bool,
) -> tuple[DocumentMetadata | None, BedrockUsageRecord | None, str | None]:
    if use_mock:
        start_time = datetime.now(UTC)
        candidate = _mock_pass2_review(metadata, context_packet)
        end_time = datetime.now(UTC)
        usage = _build_pass2_usage_record(
            metadata,
            run_id,
            config,
            start_time,
            end_time,
            usage_dict={},
            success=True,
        )
        return candidate, usage, None

    start_time = datetime.now(UTC)
    try:
        client = create_bedrock_runtime_client(config)
        extracted_text = _extract_for_pass2(metadata, config)
        user_prompt = render_pass2_user_prompt(
            json.dumps(metadata.model_dump(mode="json"), indent=2),
            json.dumps(context_packet, indent=2),
            extracted_text,
        )
        raw_text, usage_dict = call_converse_with_text(
            client,
            model_id=config.bedrock.model_id,
            system_prompt=load_pass2_system_prompt(),
            user_prompt=user_prompt,
            max_tokens=config.bedrock.max_tokens,
            temperature=config.bedrock.temperature,
        )
    except Exception as exc:
        end_time = datetime.now(UTC)
        usage = _build_pass2_usage_record(
            metadata,
            run_id,
            config,
            start_time,
            end_time,
            usage_dict={},
            success=False,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return None, usage, str(exc)

    end_time = datetime.now(UTC)
    parsed = _parse_json_object(raw_text)
    if parsed is None:
        usage = _build_pass2_usage_record(
            metadata,
            run_id,
            config,
            start_time,
            end_time,
            usage_dict=usage_dict,
            success=False,
            error_type="pass2_invalid_json",
            error_message="Pass 2 response could not be parsed as JSON",
        )
        return None, usage, "Pass 2 response could not be parsed as JSON"

    parsed = normalize_metadata_output(parsed)
    _inject_pass2_system_fields(parsed, metadata)
    try:
        candidate = DocumentMetadata.model_validate(parsed)
    except Exception as exc:
        usage = _build_pass2_usage_record(
            metadata,
            run_id,
            config,
            start_time,
            end_time,
            usage_dict=usage_dict,
            success=False,
            error_type="pass2_validation_failed",
            error_message=str(exc),
        )
        return None, usage, str(exc)

    usage = _build_pass2_usage_record(
        metadata,
        run_id,
        config,
        start_time,
        end_time,
        usage_dict=usage_dict,
        success=True,
    )
    return candidate, usage, None


def _mock_pass2_review(
    metadata: DocumentMetadata,
    context_packet: dict[str, Any],
) -> DocumentMetadata:
    data = metadata.model_dump(mode="json")
    _inject_pass2_system_fields(data, metadata)
    notes = list(data.get("processing_notes") or [])
    notes.append("generated_by: mock_bedrock_pass2")
    notes.append("pass2_context_used: branch metadata and neighboring documents")

    file_name = metadata.system.file_name_original.lower()
    if "support letter" in file_name or metadata.document_identity.document_role in {
        DocumentRole.letter_of_support,
        DocumentRole.unknown,
    }:
        data["document_identity"]["document_category"] = DocumentCategory.partner_document
        data["document_identity"]["document_role"] = DocumentRole.letter_of_support
        data["document_identity"]["origin_type"] = OriginType.generated_response
        data["confidence"]["document_category"] = max(
            float(metadata.confidence.document_category), 0.92
        )
        data["confidence"]["document_role"] = max(float(metadata.confidence.document_role), 0.95)
        data["confidence"]["origin_type"] = max(float(metadata.confidence.origin_type), 0.88)

    branch_signals = context_packet.get("preliminary_branch_signals", {})
    for field in ("canonical_proposal_name", "agency", "program"):
        current_value = data["proposal_context"].get(field)
        suggested = branch_signals.get(field)
        if _is_unknown(current_value) and not _is_unknown(suggested):
            data["proposal_context"][field] = suggested

    if _is_unknown(data["proposal_context"].get("canonical_proposal_name")):
        data["proposal_context"]["canonical_proposal_name"] = metadata.system.proposal_branch
    data["confidence"]["canonical_proposal_name"] = max(
        float(metadata.confidence.canonical_proposal_name), 0.9
    )
    data["confidence"]["agency"] = max(float(metadata.confidence.agency), 0.85)
    data["confidence"]["program"] = max(float(metadata.confidence.program), 0.85)
    data["confidence"]["include_in_future_rag"] = max(
        float(metadata.confidence.include_in_future_rag), 0.8
    )
    data["processing_notes"] = notes
    data.setdefault("fields_needing_review", [])
    data.setdefault("questions_for_user", [])
    return DocumentMetadata.model_validate(data)


def _merge_pass2_candidate(
    pass1_metadata: DocumentMetadata,
    pass2_candidate: DocumentMetadata,
    *,
    threshold: float,
) -> tuple[DocumentMetadata, list[dict[str, str]]]:
    pass1_data = pass1_metadata.model_dump(mode="json")
    pass2_data = pass2_candidate.model_dump(mode="json")
    merged = json.loads(json.dumps(pass1_data))
    changes: list[dict[str, str]] = []

    for value_path, confidence_path in _MERGE_FIELD_SPECS:
        pass1_value = _get_nested(pass1_data, value_path)
        pass2_value = _get_nested(pass2_data, value_path)
        pass1_conf = float(_get_nested(pass1_data, confidence_path) or 0.0)
        pass2_conf = float(_get_nested(pass2_data, confidence_path) or 0.0)
        field_name = ".".join(value_path)

        if pass1_value == pass2_value:
            if pass2_conf > pass1_conf:
                _set_nested(merged, confidence_path, pass2_conf)
                changes.append(
                    _change_row(
                        pass1_metadata.document_id,
                        ".".join(confidence_path),
                        pass1_conf,
                        pass2_conf,
                        pass1_conf,
                        pass2_conf,
                        "confidence_increased_with_same_value",
                    )
                )
            continue

        if _should_adopt_pass2_value(
            pass1_value,
            pass2_value,
            pass1_conf,
            pass2_conf,
            threshold=threshold,
            pass2_has_explanation=bool(pass2_data.get("processing_notes")),
        ):
            _set_nested(merged, value_path, pass2_value)
            _set_nested(merged, confidence_path, pass2_conf)
            changes.append(
                _change_row(
                    pass1_metadata.document_id,
                    field_name,
                    pass1_value,
                    pass2_value,
                    pass1_conf,
                    pass2_conf,
                    "pass2_value_adopted",
                )
            )

    merged["system"]["processing_status"] = ProcessingStatus.processed_pass2
    merged_notes = list(
        dict.fromkeys(
            (merged.get("processing_notes") or []) + pass2_data.get("processing_notes", [])
        )
    )
    merged_notes.append("pass2_context_review_applied")
    merged["processing_notes"] = merged_notes
    merged["metadata_history"] = _build_metadata_history(pass1_data, pass2_data, merged)
    return DocumentMetadata.model_validate(merged), changes


def _should_adopt_pass2_value(
    pass1_value: Any,
    pass2_value: Any,
    pass1_conf: float,
    pass2_conf: float,
    *,
    threshold: float,
    pass2_has_explanation: bool,
) -> bool:
    if _is_unknown(pass2_value):
        return False
    if _is_unknown(pass1_value):
        return pass2_conf >= threshold
    if pass1_conf >= threshold:
        return pass2_has_explanation and pass2_conf > pass1_conf
    return pass2_conf > pass1_conf


def _build_metadata_history(
    pass1_data: dict[str, Any],
    pass2_data: dict[str, Any],
    merged_data: dict[str, Any],
) -> list[dict[str, Any]]:
    captured_at = datetime.now(UTC).isoformat()
    return [
        {"stage": "pass1", "captured_at": captured_at, "metadata": _history_snapshot(pass1_data)},
        {
            "stage": "pass2_candidate",
            "captured_at": captured_at,
            "metadata": _history_snapshot(pass2_data),
        },
        {
            "stage": "pass2_merged",
            "captured_at": captured_at,
            "metadata": _history_snapshot(merged_data),
        },
    ]


def _history_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    snapshot = json.loads(json.dumps(payload))
    snapshot.pop("metadata_history", None)
    return snapshot


def _build_pass2_usage_record(
    metadata: DocumentMetadata,
    run_id: str,
    config: RuntimeConfig,
    start_time: datetime,
    end_time: datetime,
    usage_dict: dict[str, Any],
    *,
    success: bool,
    error_type: str | None = None,
    error_message: str | None = None,
) -> BedrockUsageRecord:
    return BedrockUsageRecord(
        run_id=run_id,
        document_id=metadata.document_id,
        proposal_id=metadata.proposal_id,
        model_id=config.bedrock.model_id,
        processing_strategy=str(metadata.system.processing_strategy),
        pass_number=2,
        start_time=start_time.isoformat(),
        end_time=end_time.isoformat(),
        latency_seconds=(end_time - start_time).total_seconds(),
        input_tokens=usage_dict.get("inputTokens"),
        output_tokens=usage_dict.get("outputTokens"),
        total_tokens=usage_dict.get("totalTokens"),
        success=success,
        error_type=error_type,
        error_message=error_message,
    )


def _extract_for_pass2(metadata: DocumentMetadata, config: RuntimeConfig) -> str:
    extracted = extract_text(Path(metadata.system.source_path))
    normalized = extracted.strip()
    if len(normalized) <= config.processing.local_extract_max_chars:
        return normalized
    return normalized[: config.processing.local_extract_max_chars].rstrip()


def _inject_pass2_system_fields(data: dict[str, Any], metadata: DocumentMetadata) -> None:
    data["schema_version"] = APP_SCHEMA_VERSION
    data["document_id"] = metadata.document_id
    data["proposal_id"] = metadata.proposal_id
    data["run_id"] = metadata.run_id
    system = metadata.system.model_dump(mode="json")
    system["processing_status"] = ProcessingStatus.processed_pass2
    data["system"] = system


def _parse_json_object(raw_text: str) -> dict[str, Any] | None:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _get_nested(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _set_nested(payload: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    current = payload
    for key in path[:-1]:
        next_value = current.setdefault(key, {})
        if not isinstance(next_value, dict):
            next_value = {}
            current[key] = next_value
        current = next_value
    current[path[-1]] = value


def _is_unknown(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"", "unknown"}
    return False


def _most_common_known(values: Any) -> Any:
    candidates = [value for value in values if not _is_unknown(value)]
    if not candidates:
        return None
    return Counter(candidates).most_common(1)[0][0]


def _change_row(
    document_id: str,
    field_path: str,
    old_value: Any,
    new_value: Any,
    old_confidence: float,
    new_confidence: float,
    reason: str,
) -> dict[str, str]:
    return {
        "document_id": document_id,
        "field_path": field_path,
        "old_value": json.dumps(old_value, sort_keys=True),
        "new_value": json.dumps(new_value, sort_keys=True),
        "old_confidence": f"{old_confidence:.2f}",
        "new_confidence": f"{new_confidence:.2f}",
        "reason": reason,
    }


def _write_pass2_report(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "document_id",
                "field_path",
                "old_value",
                "new_value",
                "old_confidence",
                "new_confidence",
                "reason",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
