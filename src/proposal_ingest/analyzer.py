"""Batch document analysis — runs mock or real Bedrock for each eligible inventory record."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from proposal_ingest.bedrock_client import (
    BEDROCK_DOCUMENT_FORMATS,
    call_converse_with_document,
    call_converse_with_text,
    create_bedrock_runtime_client,
)
from proposal_ingest.config import RuntimeConfig
from proposal_ingest.extractors import count_excel_nonempty_cells, extract_text
from proposal_ingest.logging_utils import get_logger
from proposal_ingest.metadata_store import MetadataStore
from proposal_ingest.mock_bedrock import analyze_document_mock
from proposal_ingest.prompts import render_repair_prompt, render_user_prompt, load_system_prompt
from proposal_ingest.schemas import (
    APP_SCHEMA_VERSION,
    BedrockUsageRecord,
    DocumentMetadata,
    InventoryRecord,
    ProcessingStatus,
    ProcessingStrategy,
    SystemMetadata,
)

logger = get_logger("analyzer")

# Excel extensions that may qualify for the tiny/simple direct-upload path.
_EXCEL_EXTENSIONS = {".xlsx", ".xls"}


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class SingleFileResult:
    """Outcome of processing one document file."""

    record: InventoryRecord
    metadata: DocumentMetadata | None
    success: bool
    error_message: str | None = None
    raw_response: str | None = None
    usage: BedrockUsageRecord | None = None


# ---------------------------------------------------------------------------
# Strategy helpers
# ---------------------------------------------------------------------------


def _is_tiny_excel(path: Path, config: RuntimeConfig) -> bool:
    """Return True when an Excel file qualifies for the direct-upload path.

    Criteria (all must hold):
    - File size <= tiny_excel_max_size_mb
    - Sheet count <= tiny_excel_max_sheets
    - Non-empty cell count <= tiny_excel_max_nonempty_cells
    """
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > config.processing.tiny_excel_max_size_mb:
        return False
    sheet_count, nonempty_cells = count_excel_nonempty_cells(path)
    if sheet_count < 0:
        # Could not read the workbook; fall back to local extraction.
        return False
    return (
        sheet_count <= config.processing.tiny_excel_max_sheets
        and nonempty_cells <= config.processing.tiny_excel_max_nonempty_cells
    )


def _decide_strategy(path: Path, record: InventoryRecord, config: RuntimeConfig) -> str:
    """Return the effective processing strategy for this file.

    Rules (match first):
    1. Excel + tiny/simple → direct_bedrock (direct upload allowed)
    2. Excel + not tiny  → local_extract_then_bedrock
    3. Extension in BEDROCK_DOCUMENT_FORMATS + size <= max_direct_upload_mb → direct_bedrock
    4. Otherwise → local_extract_then_bedrock
    """
    ext = record.extension.lower()
    if ext in _EXCEL_EXTENSIONS:
        if _is_tiny_excel(path, config):
            return "direct_bedrock"
        return "local_extract_then_bedrock"

    if ext in BEDROCK_DOCUMENT_FORMATS:
        size_mb = record.size_bytes / (1024 * 1024)
        if size_mb <= config.bedrock.max_direct_upload_mb:
            return "direct_bedrock"

    return "local_extract_then_bedrock"


# ---------------------------------------------------------------------------
# JSON parsing helpers
# ---------------------------------------------------------------------------


def _strip_markdown_fences(text: str) -> str:
    """Remove leading/trailing markdown code fences from a model response."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Drop the opening fence line (e.g. ```json)
        lines = lines[1:]
        # Drop the closing fence if present
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def _parse_json_response(raw_text: str) -> dict[str, Any] | None:
    """Try to parse raw model output as JSON. Returns None on failure."""
    cleaned = _strip_markdown_fences(raw_text)
    try:
        result = json.loads(cleaned)
        return result if isinstance(result, dict) else None
    except json.JSONDecodeError:
        return None


def _inject_system_fields(
    data: dict[str, Any],
    record: InventoryRecord,
    run_id: str,
    processing_strategy: str,
) -> dict[str, Any]:
    """Override pipeline-controlled fields that the model must not invent."""
    data["schema_version"] = APP_SCHEMA_VERSION
    data["document_id"] = record.document_id
    data["proposal_id"] = record.proposal_id
    data["run_id"] = run_id
    data["system"] = SystemMetadata(
        source_path=record.source_path,
        relative_path=record.relative_path,
        year_folder=record.year_folder,
        proposal_branch=record.proposal_branch,
        file_name_original=record.file_name_original,
        file_name_safe=record.file_name_safe,
        extension=record.extension,
        size_bytes=record.size_bytes,
        modified_time=record.modified_time,
        sha256=record.sha256,
        processing_strategy=ProcessingStrategy(processing_strategy),
        processing_status=ProcessingStatus.processed_pass1,
    ).model_dump()
    # Auto-assign question_ids for any questions the model generated.
    for i, question in enumerate(data.get("questions_for_user", [])):
        if isinstance(question, dict) and "question_id" not in question:
            question["question_id"] = f"q_{record.document_id}_{i + 1:03d}"
    return data


def _validate_metadata(data: dict[str, Any]) -> tuple[DocumentMetadata | None, str | None]:
    """Validate a parsed JSON dict as DocumentMetadata. Returns (metadata, error_str)."""
    try:
        return DocumentMetadata.model_validate(data), None
    except ValidationError as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# Bedrock call wrapper
# ---------------------------------------------------------------------------


def _call_bedrock(
    client: Any,
    path: Path,
    record: InventoryRecord,
    system_prompt: str,
    user_prompt: str,
    strategy: str,
    config: RuntimeConfig,
) -> tuple[str, dict[str, Any]]:
    """Dispatch to the correct Bedrock Converse call based on strategy.

    Returns (raw_response_text, usage_dict).
    """
    if strategy == "direct_bedrock":
        doc_format = BEDROCK_DOCUMENT_FORMATS.get(record.extension.lower(), "txt")
        file_bytes = path.read_bytes()
        return call_converse_with_document(
            client,
            model_id=config.bedrock.model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            file_bytes=file_bytes,
            doc_format=doc_format,
            doc_name=record.file_name_original,
            max_tokens=config.bedrock.max_tokens,
            temperature=config.bedrock.temperature,
        )
    else:
        extracted = extract_text(path)
        full_prompt = _build_local_extract_prompt(
            user_prompt,
            extracted,
            max_chars=config.processing.local_extract_max_chars,
        )
        return call_converse_with_text(
            client,
            model_id=config.bedrock.model_id,
            system_prompt=system_prompt,
            user_prompt=full_prompt,
            max_tokens=config.bedrock.max_tokens,
            temperature=config.bedrock.temperature,
        )


def _build_local_extract_prompt(user_prompt: str, extracted_text: str, *, max_chars: int) -> str:
    """Build the text-only prompt payload for locally extracted document content."""
    if not extracted_text:
        return f"{user_prompt}\n\n---\n(No text could be extracted from this file.)"

    normalized_text = extracted_text.strip()
    if len(normalized_text) <= max_chars:
        payload_text = normalized_text
    else:
        payload_text = (
            "[Truncated extracted text from "
            f"{len(normalized_text)} to {max_chars} characters before sending to Bedrock.]\n\n"
            f"{normalized_text[:max_chars].rstrip()}"
        )

    return f"{user_prompt}\n\n---\nExtracted document text:\n\n{payload_text}"


# ---------------------------------------------------------------------------
# Public single-file processor
# ---------------------------------------------------------------------------


def process_single_file(
    file_path: Path,
    record: InventoryRecord,
    run_dir: Path,
    run_id: str,
    config: RuntimeConfig,
    *,
    use_mock: bool,
    save_raw_responses: bool,
    dry_run: bool = False,
) -> SingleFileResult:
    """Analyze one document and write its metadata to run_dir.

    Args:
        file_path: Absolute path to the document file.
        record: Pre-built InventoryRecord for this file.
        run_dir: Run-scoped output directory (already created or creatable).
        run_id: Identifier for the current run.
        config: Merged runtime configuration.
        use_mock: When True, call analyze_document_mock instead of Bedrock.
        save_raw_responses: When True, write the raw Bedrock response to disk.
        dry_run: When True, print strategy info and skip all writes/Bedrock calls.

    Returns:
        SingleFileResult with metadata set on success or None on failure.
    """
    strategy = _decide_strategy(file_path, record, config)

    if dry_run:
        logger.info("[dry-run] Would process %s using strategy=%s", file_path.name, strategy)
        return SingleFileResult(record=record, metadata=None, success=True)

    store = MetadataStore(run_dir)

    # ---- Mock path -------------------------------------------------------
    if use_mock:
        metadata = analyze_document_mock(record, run_id)
        store.write_document_metadata(metadata)
        return SingleFileResult(record=record, metadata=metadata, success=True)

    # ---- Real Bedrock path -----------------------------------------------
    system_prompt = load_system_prompt()
    pipeline_context = {
        "document_id": record.document_id,
        "proposal_id": record.proposal_id,
        "source_path": record.source_path,
        "file_name_original": record.file_name_original,
        "year_folder": record.year_folder,
        "proposal_branch": record.proposal_branch,
        "extension": record.extension,
        "size_bytes": record.size_bytes,
        "processing_strategy": strategy,
    }
    user_prompt = render_user_prompt(json.dumps(pipeline_context, indent=2))

    client = create_bedrock_runtime_client(config)
    start_time = datetime.now(UTC)

    try:
        raw_text, usage_dict = _call_bedrock(
            client, file_path, record, system_prompt, user_prompt, strategy, config
        )
    except Exception as exc:
        end_time = datetime.now(UTC)
        error_msg = str(exc)
        logger.error("Bedrock call failed for %s: %s", file_path.name, error_msg)
        usage_rec = _build_usage_record(
            record,
            run_id,
            config,
            strategy,
            start_time,
            end_time,
            usage_dict={},
            success=False,
            error_type=type(exc).__name__,
            error_message=error_msg,
        )
        store.write_usage_record(usage_rec)
        store.write_failure_record(
            record.document_id,
            "bedrock_call_failed",
            {"file": str(file_path), "error": error_msg},
        )
        return SingleFileResult(
            record=record,
            metadata=None,
            success=False,
            error_message=error_msg,
            usage=usage_rec,
        )

    end_time = datetime.now(UTC)

    if save_raw_responses:
        store.write_raw_response(record.document_id, pass_number=1, raw_text=raw_text)

    # ---- Parse and validate response -------------------------------------
    parsed = _parse_json_response(raw_text)
    if parsed is None:
        error_msg = "Model response could not be parsed as JSON"
        logger.warning("%s for %s", error_msg, file_path.name)
    else:
        _inject_system_fields(parsed, record, run_id, strategy)
        validated_meta: DocumentMetadata | None
        validated_meta, validation_error = _validate_metadata(parsed)
        if validated_meta is not None:
            usage_rec = _build_usage_record(
                record,
                run_id,
                config,
                strategy,
                start_time,
                end_time,
                usage_dict=usage_dict,
                success=True,
            )
            store.write_document_metadata(validated_meta)
            store.write_usage_record(usage_rec)
            return SingleFileResult(
                record=record,
                metadata=validated_meta,
                success=True,
                raw_response=raw_text,
                usage=usage_rec,
            )
        error_msg = validation_error or "Pydantic validation failed"
        logger.warning("Validation failed for %s: %s", file_path.name, error_msg)

    # ---- Repair attempt --------------------------------------------------
    if config.bedrock.retry_invalid_json_once:
        logger.info("Running repair prompt for %s", file_path.name)
        repair_prompt = render_repair_prompt(
            validation_error=error_msg or "JSON parse error",
            raw_model_response=raw_text,
        )
        try:
            repair_raw, repair_usage = call_converse_with_text(
                client,
                model_id=config.bedrock.model_id,
                system_prompt=system_prompt,
                user_prompt=repair_prompt,
                max_tokens=config.bedrock.max_tokens,
                temperature=config.bedrock.temperature,
            )
        except Exception as exc:
            repair_end = datetime.now(UTC)
            logger.error("Repair call failed for %s: %s", file_path.name, exc)
            _save_failure(
                store,
                record,
                run_id,
                config,
                strategy,
                start_time,
                repair_end,
                usage_dict={},
                error_type="repair_bedrock_failed",
                error_message=str(exc),
                raw_response=raw_text,
            )
            return SingleFileResult(
                record=record,
                metadata=None,
                success=False,
                error_message=str(exc),
                raw_response=raw_text,
            )

        repair_end = datetime.now(UTC)
        if save_raw_responses:
            store.write_raw_response(record.document_id, pass_number=2, raw_text=repair_raw)

        repair_parsed = _parse_json_response(repair_raw)
        if repair_parsed is not None:
            _inject_system_fields(repair_parsed, record, run_id, strategy)
            repaired_meta: DocumentMetadata | None
            repaired_meta, repair_error = _validate_metadata(repair_parsed)
            if repaired_meta is not None:
                # Merge usage: sum tokens across both calls.
                merged_usage = _merge_usage(usage_dict, repair_usage)
                usage_rec = _build_usage_record(
                    record,
                    run_id,
                    config,
                    strategy,
                    start_time,
                    repair_end,
                    usage_dict=merged_usage,
                    success=True,
                )
                store.write_document_metadata(repaired_meta)
                store.write_usage_record(usage_rec)
                return SingleFileResult(
                    record=record,
                    metadata=repaired_meta,
                    success=True,
                    raw_response=repair_raw,
                    usage=usage_rec,
                )
            error_msg = repair_error or "Repair validation failed"

    # ---- Save failure record ---------------------------------------------
    _save_failure(
        store,
        record,
        run_id,
        config,
        strategy,
        start_time,
        end_time,
        usage_dict=usage_dict,
        error_type="validation_failed",
        error_message=error_msg or "Unknown error",
        raw_response=raw_text,
    )
    return SingleFileResult(
        record=record,
        metadata=None,
        success=False,
        error_message=error_msg,
        raw_response=raw_text,
    )


# ---------------------------------------------------------------------------
# Usage record helpers
# ---------------------------------------------------------------------------


def _build_usage_record(
    record: InventoryRecord,
    run_id: str,
    config: RuntimeConfig,
    strategy: str,
    start_time: datetime,
    end_time: datetime,
    usage_dict: dict[str, Any],
    *,
    success: bool,
    error_type: str | None = None,
    error_message: str | None = None,
    pass_number: int = 1,
) -> BedrockUsageRecord:
    return BedrockUsageRecord(
        run_id=run_id,
        document_id=record.document_id,
        proposal_id=record.proposal_id,
        model_id=config.bedrock.model_id,
        processing_strategy=strategy,
        pass_number=pass_number,
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


def _merge_usage(u1: dict[str, Any], u2: dict[str, Any]) -> dict[str, Any]:
    """Sum token counts across two usage dicts."""

    def _add(key: str) -> int | None:
        a, b = u1.get(key), u2.get(key)
        if a is None and b is None:
            return None
        return (a or 0) + (b or 0)

    return {
        "inputTokens": _add("inputTokens"),
        "outputTokens": _add("outputTokens"),
        "totalTokens": _add("totalTokens"),
    }


def _save_failure(
    store: MetadataStore,
    record: InventoryRecord,
    run_id: str,
    config: RuntimeConfig,
    strategy: str,
    start_time: datetime,
    end_time: datetime,
    usage_dict: dict[str, Any],
    error_type: str,
    error_message: str,
    raw_response: str,
) -> None:
    usage_rec = _build_usage_record(
        record,
        run_id,
        config,
        strategy,
        start_time,
        end_time,
        usage_dict=usage_dict,
        success=False,
        error_type=error_type,
        error_message=error_message,
    )
    store.write_usage_record(usage_rec)
    store.write_failure_record(
        record.document_id,
        error_type,
        {
            "error_message": error_message,
            "raw_response_preview": raw_response[:500] if raw_response else "",
        },
    )


# ---------------------------------------------------------------------------
# Batch helpers (pre-Phase 7 skeleton, already used by CLI run-all / analyze)
# ---------------------------------------------------------------------------


def find_latest_inventory_jsonl(output_root: Path) -> Path | None:
    """Return the most recent file_inventory.jsonl under output_root/logs, or None."""
    logs_dir = output_root / "logs"
    if not logs_dir.is_dir():
        return None
    candidates = sorted(
        logs_dir.glob("run_*/inventory/file_inventory.jsonl"),
        key=lambda p: p.parts[-3],  # sort by run_id dir name
    )
    return candidates[-1] if candidates else None


def load_inventory_jsonl(path: Path) -> list[InventoryRecord]:
    """Deserialize an inventory JSONL file into InventoryRecord objects."""
    records: list[InventoryRecord] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(InventoryRecord.model_validate(json.loads(line)))
    return records


def analyze_inventory(
    run_dir: Path,
    inventory_records: list[InventoryRecord],
    run_id: str,
    *,
    use_mock: bool,
) -> list[DocumentMetadata]:
    """Analyze eligible inventory records and write metadata to run_dir.

    Args:
        run_dir: The run-scoped output directory (must already exist or be creatable).
        inventory_records: All records from the scan inventory.
        run_id: The run identifier to embed in each DocumentMetadata record.
        use_mock: When True, calls ``analyze_document_mock``; when False, raises
                  NotImplementedError (real Bedrock batch is Phase 7).

    Returns:
        List of DocumentMetadata objects produced (eligible documents only).
    """
    if not use_mock:
        raise NotImplementedError(
            "Real Bedrock batch analysis is not yet implemented. Use --mock-bedrock."
        )

    store = MetadataStore(run_dir)
    results: list[DocumentMetadata] = []

    eligible = [r for r in inventory_records if r.eligible_for_processing]

    for record in eligible:
        metadata = analyze_document_mock(record, run_id)
        store.write_document_metadata(metadata)
        results.append(metadata)

    _finalize_run_manifest(run_dir, use_mock=use_mock)

    return results


def _finalize_run_manifest(run_dir: Path, *, use_mock: bool) -> None:
    """Update an existing run manifest to reflect analysis mode."""
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        return

    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["mock_bedrock"] = use_mock
    raw["command"] = "analyze"
    manifest_path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def analyze_from_output_root(
    output_root: Path,
    *,
    use_mock: bool,
) -> tuple[Path, list[DocumentMetadata]]:
    """Locate the latest scan inventory under output_root and analyze it.

    Returns:
        (run_dir, list of DocumentMetadata) for the run that was analyzed.

    Raises:
        FileNotFoundError: if no inventory JSONL is found under output_root/logs/.
    """
    inventory_path = find_latest_inventory_jsonl(output_root)
    if inventory_path is None:
        raise FileNotFoundError(
            f"No file_inventory.jsonl found under {output_root}/logs/. "
            "Run 'proposal-ingest scan' first."
        )

    run_dir = inventory_path.parent.parent  # .../logs/run_id/inventory/.. -> run_id dir
    run_id = run_dir.name

    records = load_inventory_jsonl(inventory_path)
    results = analyze_inventory(run_dir, records, run_id, use_mock=use_mock)

    return run_dir, results
