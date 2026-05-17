"""Tests for Phase 6 — single-file document processor."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from proposal_ingest.analyzer import (
    _build_local_extract_prompt,
    _decide_strategy,
    _inject_system_fields,
    _parse_json_response,
    _strip_markdown_fences,
    process_single_file,
)
from proposal_ingest.cli import app
from proposal_ingest.config import load_runtime_config
from proposal_ingest.extractors import extract_text
from proposal_ingest.model_output import normalize_metadata_output
from proposal_ingest.mock_bedrock import analyze_document_mock
from proposal_ingest.prompts import (
    load_system_prompt,
    load_user_prompt_template,
    render_repair_prompt,
    render_user_prompt,
)
from proposal_ingest.schemas import (
    DocumentCategory,
    DocumentMetadata,
    DocumentRole,
    OriginType,
    InventoryRecord,
    ProcessingStatus,
)

_runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_inventory_record(
    file_name: str = "Technical Volume.pdf",
    extension: str = ".pdf",
    size_bytes: int = 1024,
    eligible: bool = True,
) -> InventoryRecord:
    sha = hashlib.sha256(file_name.encode()).hexdigest()
    return InventoryRecord(
        document_id=f"doc_{sha[:16]}",
        proposal_id="prop_2025-test__abcd1234",
        source_path=f"C:/source/2025/Test Proposal/{file_name}",
        relative_path=f"2025/Test Proposal/{file_name}",
        year_folder="2025",
        proposal_branch="Test Proposal",
        file_name_original=file_name,
        file_name_safe=file_name.replace(" ", "_"),
        extension=extension,
        size_bytes=size_bytes,
        modified_time="2026-05-16T12:00:00+00:00",
        sha256=sha,
        eligible_for_processing=eligible,
        processing_strategy="direct_bedrock" if eligible else "inventory_only",
        processing_status="pending_analysis" if eligible else "inventory_only",
        skip_reason=None if eligible else "unsupported_file_type",
    )


# ---------------------------------------------------------------------------
# prompts.py
# ---------------------------------------------------------------------------


def test_load_system_prompt_returns_nonempty_string() -> None:
    text = load_system_prompt()
    assert isinstance(text, str)
    assert len(text) > 10


def test_load_user_prompt_template_contains_placeholder() -> None:
    template = load_user_prompt_template()
    assert "{{PIPELINE_CONTEXT_JSON}}" in template
    assert "{{DOCUMENT_METADATA_TEMPLATE_JSON}}" in template


def test_render_user_prompt_substitutes_context() -> None:
    context_json = '{"document_id": "doc_abc123"}'
    rendered = render_user_prompt(context_json)
    assert "{{PIPELINE_CONTEXT_JSON}}" not in rendered
    assert "{{DOCUMENT_METADATA_TEMPLATE_JSON}}" not in rendered
    assert '"document_id": "doc_abc123"' in rendered
    assert '"canonical_document_title": "unknown"' in rendered


def test_render_repair_prompt_substitutes_both_placeholders() -> None:
    rendered = render_repair_prompt("some error", "bad json response")
    assert "{{VALIDATION_ERROR}}" not in rendered
    assert "{{RAW_MODEL_RESPONSE}}" not in rendered
    assert "{{DOCUMENT_METADATA_TEMPLATE_JSON}}" not in rendered
    assert "some error" in rendered
    assert "bad json response" in rendered
    assert '"canonical_document_title": "unknown"' in rendered


# ---------------------------------------------------------------------------
# extractors.py
# ---------------------------------------------------------------------------


def test_extract_text_txt(tmp_path: Path) -> None:
    f = tmp_path / "hello.txt"
    f.write_text("Hello, world!", encoding="utf-8")
    assert extract_text(f) == "Hello, world!"


def test_extract_text_md(tmp_path: Path) -> None:
    f = tmp_path / "notes.md"
    f.write_text("# Title\nsome text", encoding="utf-8")
    result = extract_text(f)
    assert "Title" in result


def test_extract_text_csv(tmp_path: Path) -> None:
    f = tmp_path / "data.csv"
    f.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    result = extract_text(f)
    assert "a,b,c" in result


def test_extract_text_unsupported_returns_empty(tmp_path: Path) -> None:
    f = tmp_path / "image.png"
    f.write_bytes(b"\x89PNG\r\n")
    assert extract_text(f) == ""


def test_extract_text_nonexistent_returns_empty(tmp_path: Path) -> None:
    f = tmp_path / "ghost.txt"
    # File doesn't exist — extract_text should catch the error and return ""
    assert extract_text(f) == ""


# ---------------------------------------------------------------------------
# JSON parsing helpers
# ---------------------------------------------------------------------------


def test_strip_markdown_fences_plain_json() -> None:
    raw = '{"key": "value"}'
    assert _strip_markdown_fences(raw) == raw


def test_strip_markdown_fences_with_json_fence() -> None:
    raw = '```json\n{"key": "value"}\n```'
    result = _strip_markdown_fences(raw)
    assert result == '{"key": "value"}'


def test_strip_markdown_fences_bare_fence() -> None:
    raw = '```\n{"key": "value"}\n```'
    result = _strip_markdown_fences(raw)
    assert result == '{"key": "value"}'


def test_parse_json_response_valid() -> None:
    raw = '{"foo": "bar"}'
    result = _parse_json_response(raw)
    assert result == {"foo": "bar"}


def test_parse_json_response_with_fences() -> None:
    raw = '```json\n{"foo": "bar"}\n```'
    result = _parse_json_response(raw)
    assert result == {"foo": "bar"}


def test_parse_json_response_invalid_returns_none() -> None:
    assert _parse_json_response("not json at all") is None


def test_parse_json_response_array_returns_none() -> None:
    # We only accept top-level objects, not arrays.
    assert _parse_json_response("[1, 2, 3]") is None


def test_normalize_metadata_output_maps_common_enum_aliases() -> None:
    record = _make_inventory_record()
    payload = analyze_document_mock(record, "run_norm_001").model_dump(mode="json")
    payload["document_identity"]["document_category"] = "budget"
    payload["document_identity"]["document_role"] = "partner_support_letter"
    payload["document_identity"]["origin_type"] = "generated_by_team"
    payload["opportunity_treatment"]["recommended_rag_treatment"] = "full_ingest"
    payload["proposal_context"]["program"] = "SBIR Phase I"
    payload["proposal_context"]["status"] = "pre-submission"

    normalized = normalize_metadata_output(payload)

    assert normalized["document_identity"]["document_category"] == "budget_financial"
    assert normalized["document_identity"]["document_role"] == "letter_of_support"
    assert normalized["document_identity"]["origin_type"] == "generated_response"
    assert normalized["opportunity_treatment"]["recommended_rag_treatment"] == "full_document"
    assert normalized["proposal_context"]["program"] == "SBIR"
    assert normalized["proposal_context"]["status"] == "drafted"


def test_build_local_extract_prompt_truncates_large_extraction() -> None:
    user_prompt = "Analyze this document"
    extracted = "A" * 80

    prompt = _build_local_extract_prompt(user_prompt, extracted, max_chars=40)

    assert "Truncated extracted text from 80 to 40 characters" in prompt
    assert ("A" * 80) not in prompt
    assert ("A" * 40) in prompt


# ---------------------------------------------------------------------------
# _inject_system_fields
# ---------------------------------------------------------------------------


def test_inject_system_fields_overrides_document_id() -> None:
    record = _make_inventory_record()
    data: dict = {"document_id": "wrong_id", "proposal_id": "wrong_pid"}
    _inject_system_fields(data, record, "run_test_999", "direct_bedrock")
    assert data["document_id"] == record.document_id
    assert data["proposal_id"] == record.proposal_id
    assert data["run_id"] == "run_test_999"
    assert data["system"]["processing_status"] == ProcessingStatus.processed_pass1


def test_inject_system_fields_auto_assigns_question_ids() -> None:
    record = _make_inventory_record()
    data: dict = {
        "questions_for_user": [
            {"question": "What is this?", "priority": "high"},
        ]
    }
    _inject_system_fields(data, record, "run_x", "direct_bedrock")
    q = data["questions_for_user"][0]
    assert "question_id" in q
    assert q["question_id"].startswith("q_")


# ---------------------------------------------------------------------------
# _decide_strategy
# ---------------------------------------------------------------------------


def test_decide_strategy_pdf_small_is_direct(tmp_path: Path) -> None:
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF fake")
    record = _make_inventory_record("doc.pdf", ".pdf", size_bytes=f.stat().st_size)
    cfg = load_runtime_config()
    assert _decide_strategy(f, record, cfg) == "direct_bedrock"


def test_decide_strategy_large_pdf_is_local_extract(tmp_path: Path) -> None:
    f = tmp_path / "large.pdf"
    # Write a file larger than max_direct_upload_mb (20 MB default)
    f.write_bytes(b"x" * (21 * 1024 * 1024))
    record = _make_inventory_record("large.pdf", ".pdf", size_bytes=f.stat().st_size)
    cfg = load_runtime_config()
    assert _decide_strategy(f, record, cfg) == "local_extract_then_bedrock"


# ---------------------------------------------------------------------------
# process_single_file — mock mode
# ---------------------------------------------------------------------------


def test_process_single_file_mock_mode_succeeds(tmp_path: Path) -> None:
    f = tmp_path / "Technical Volume.pdf"
    f.write_bytes(b"%PDF fake content")
    record = _make_inventory_record("Technical Volume.pdf", ".pdf", size_bytes=f.stat().st_size)
    run_dir = tmp_path / "run_test"
    run_dir.mkdir()
    cfg = load_runtime_config()

    result = process_single_file(
        file_path=f,
        record=record,
        run_dir=run_dir,
        run_id="run_test_001",
        config=cfg,
        use_mock=True,
        save_raw_responses=False,
    )

    assert result.success is True
    assert isinstance(result.metadata, DocumentMetadata)
    assert result.metadata.document_id == record.document_id
    # Metadata JSON should be saved to disk.
    by_id_dir = run_dir / "document_metadata" / "by_document_id"
    assert (by_id_dir / f"{record.document_id}.json").exists()


def test_process_single_file_mock_mode_dry_run(tmp_path: Path) -> None:
    """Dry-run must return success=True and write nothing to disk."""
    f = tmp_path / "Budget.xlsx"
    f.write_bytes(b"fake xlsx")
    record = _make_inventory_record("Budget.xlsx", ".xlsx", size_bytes=f.stat().st_size)
    run_dir = tmp_path / "run_dry"
    cfg = load_runtime_config()

    result = process_single_file(
        file_path=f,
        record=record,
        run_dir=run_dir,
        run_id="run_dry_001",
        config=cfg,
        use_mock=True,
        save_raw_responses=False,
        dry_run=True,
    )

    assert result.success is True
    assert result.metadata is None
    assert not run_dir.exists()  # nothing written


# ---------------------------------------------------------------------------
# CLI process-file — mock and dry-run
# ---------------------------------------------------------------------------


def test_cli_process_file_mock_mode(tmp_path: Path) -> None:
    f = tmp_path / "Technical Volume.pdf"
    f.write_bytes(b"%PDF fake")
    output_root = tmp_path / "output"

    result = _runner.invoke(
        app,
        [
            "process-file",
            "--file",
            str(f),
            "--output-root",
            str(output_root),
            "--mock-bedrock",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "process-file complete" in result.output
    run_dirs = list((output_root / "logs").glob("run_*"))
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "run_manifest.json").exists()


def test_cli_process_file_dry_run(tmp_path: Path) -> None:
    f = tmp_path / "Abstract.docx"
    f.write_bytes(b"fake docx")
    output_root = tmp_path / "output"

    result = _runner.invoke(
        app,
        [
            "process-file",
            "--file",
            str(f),
            "--output-root",
            str(output_root),
            "--mock-bedrock",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    # Nothing should be written under output_root.
    assert not output_root.exists()


def test_cli_process_file_missing_file(tmp_path: Path) -> None:
    result = _runner.invoke(
        app,
        [
            "process-file",
            "--file",
            str(tmp_path / "ghost.pdf"),
            "--output-root",
            str(tmp_path / "output"),
            "--mock-bedrock",
        ],
    )
    assert result.exit_code != 0
    assert "not found" in result.output


# ---------------------------------------------------------------------------
# process_single_file — real Bedrock path (mocked boto3)
# ---------------------------------------------------------------------------


def _make_valid_bedrock_response(record: InventoryRecord) -> dict:
    """Build a minimal JSON payload that passes DocumentMetadata validation."""
    return {
        "document_identity": {
            "canonical_document_title": "Test Document",
            "document_category": "proposal_response",
            "document_role": "technical_volume",
            "origin_type": "generated_response",
            "version_status": "final",
        },
        "proposal_context": {
            "canonical_proposal_name": "Test Proposal",
            "agency": "DOE",
            "program": "SBIR",
            "status": "submitted",
            "award_status": "unknown",
        },
        "content": {
            "summary_short": "A technical volume for an SBIR proposal.",
            "primary_topics": ["battery technology"],
        },
        "opportunity_treatment": {
            "opportunity_context_useful": False,
            "boilerplate_heavy": False,
            "recommended_rag_treatment": "full_document",
        },
        "inclusion": {
            "include_in_clean_set": True,
            "include_in_future_rag": True,
            "rag_priority": "high",
            "include_reason": "Core technical content.",
        },
        "sensitivity": {
            "manual_review_required": False,
        },
        "confidence": {
            "document_category": 0.9,
            "document_role": 0.85,
            "origin_type": 0.9,
            "version_status": 0.8,
            "canonical_proposal_name": 0.7,
            "agency": 0.8,
            "program": 0.8,
            "status": 0.7,
            "award_status": 0.5,
            "include_in_clean_set": 0.9,
            "include_in_future_rag": 0.9,
            "rag_priority": 0.9,
        },
    }


def _fake_converse_response(text_payload: str) -> dict:
    """Build a fake Bedrock Converse response dict."""
    return {
        "output": {"message": {"content": [{"text": text_payload}]}},
        "usage": {"inputTokens": 100, "outputTokens": 200, "totalTokens": 300},
    }


def test_process_single_file_real_bedrock_success(tmp_path: Path) -> None:
    """Real Bedrock path: valid JSON response → DocumentMetadata saved."""
    f = tmp_path / "Technical Volume.pdf"
    f.write_bytes(b"%PDF fake content")
    record = _make_inventory_record("Technical Volume.pdf", ".pdf", size_bytes=f.stat().st_size)
    run_dir = tmp_path / "run_real"
    run_dir.mkdir()
    cfg = load_runtime_config()

    valid_payload = json.dumps(_make_valid_bedrock_response(record))
    fake_response = _fake_converse_response(valid_payload)

    mock_client = MagicMock()
    mock_client.converse.return_value = fake_response

    with patch("proposal_ingest.analyzer.create_bedrock_runtime_client", return_value=mock_client):
        result = process_single_file(
            file_path=f,
            record=record,
            run_dir=run_dir,
            run_id="run_real_001",
            config=cfg,
            use_mock=False,
            save_raw_responses=True,
        )

    assert result.success is True, result.error_message
    assert isinstance(result.metadata, DocumentMetadata)
    assert result.metadata.document_id == record.document_id
    # Usage record written
    usage_file = run_dir / "usage" / "bedrock_usage.jsonl"
    assert usage_file.exists()
    usage_line = json.loads(usage_file.read_text(encoding="utf-8").strip())
    assert usage_line["success"] is True
    assert usage_line["input_tokens"] == 100
    # Raw response saved
    raw_file = run_dir / "raw_responses" / f"{record.document_id}_pass1.txt"
    assert raw_file.exists()


def test_process_single_file_real_bedrock_uses_bedrock_safe_document_name(
    tmp_path: Path,
) -> None:
    """Direct document uploads should use a Bedrock-safe DocumentBlock name."""
    filename = "Quad_Chart.v2 [Final].pdf"
    f = tmp_path / filename
    f.write_bytes(b"%PDF fake content")
    record = _make_inventory_record(filename, ".pdf", size_bytes=f.stat().st_size)
    run_dir = tmp_path / "run_real_safe_name"
    run_dir.mkdir()
    cfg = load_runtime_config()

    valid_payload = json.dumps(_make_valid_bedrock_response(record))
    fake_response = _fake_converse_response(valid_payload)

    mock_client = MagicMock()
    mock_client.converse.return_value = fake_response

    with patch("proposal_ingest.analyzer.create_bedrock_runtime_client", return_value=mock_client):
        result = process_single_file(
            file_path=f,
            record=record,
            run_dir=run_dir,
            run_id="run_real_safe_name_001",
            config=cfg,
            use_mock=False,
            save_raw_responses=False,
        )

    assert result.success is True, result.error_message
    request_document = mock_client.converse.call_args.kwargs["messages"][0]["content"][0][
        "document"
    ]
    assert request_document["name"] == "Quad Chart v2 [Final]"


def test_process_single_file_repair_path(tmp_path: Path) -> None:
    """Bad JSON on first call → repair prompt → valid JSON on second call."""
    f = tmp_path / "Budget.pdf"
    f.write_bytes(b"%PDF fake")
    record = _make_inventory_record("Budget.pdf", ".pdf", size_bytes=f.stat().st_size)
    run_dir = tmp_path / "run_repair"
    run_dir.mkdir()
    cfg = load_runtime_config()

    bad_response = _fake_converse_response("THIS IS NOT JSON")
    valid_payload = json.dumps(_make_valid_bedrock_response(record))
    good_response = _fake_converse_response(valid_payload)

    mock_client = MagicMock()
    mock_client.converse.side_effect = [bad_response, good_response]

    with patch("proposal_ingest.analyzer.create_bedrock_runtime_client", return_value=mock_client):
        result = process_single_file(
            file_path=f,
            record=record,
            run_dir=run_dir,
            run_id="run_repair_001",
            config=cfg,
            use_mock=False,
            save_raw_responses=False,
        )

    assert result.success is True, result.error_message
    assert mock_client.converse.call_count == 2  # first call + repair


def test_process_single_file_local_extract_truncates_prompt_before_bedrock(
    tmp_path: Path,
) -> None:
    """Local extraction should cap prompt size before sending text to Bedrock."""
    f = tmp_path / "Long Technical Volume.pdf"
    f.write_bytes(b"%PDF fake")
    record = _make_inventory_record(f.name, ".pdf", size_bytes=f.stat().st_size)
    run_dir = tmp_path / "run_local_extract"
    run_dir.mkdir()
    cfg = load_runtime_config()
    cfg.processing.local_extract_max_chars = 40

    valid_payload = json.dumps(_make_valid_bedrock_response(record))
    fake_response = _fake_converse_response(valid_payload)
    mock_client = MagicMock()
    mock_client.converse.return_value = fake_response

    with (
        patch("proposal_ingest.analyzer.create_bedrock_runtime_client", return_value=mock_client),
        patch(
            "proposal_ingest.analyzer._decide_strategy", return_value="local_extract_then_bedrock"
        ),
        patch("proposal_ingest.analyzer.extract_text", return_value="A" * 80),
    ):
        result = process_single_file(
            file_path=f,
            record=record,
            run_dir=run_dir,
            run_id="run_local_extract_001",
            config=cfg,
            use_mock=False,
            save_raw_responses=False,
        )

    assert result.success is True, result.error_message
    text_content = mock_client.converse.call_args.kwargs["messages"][0]["content"][0]["text"]
    assert "Truncated extracted text from 80 to 40 characters" in text_content
    assert ("A" * 80) not in text_content
    assert ("A" * 40) in text_content


def test_process_single_file_total_failure_saves_failure_record(tmp_path: Path) -> None:
    """If both original and repair calls fail validation, a failure record is saved."""
    f = tmp_path / "Broken.pdf"
    f.write_bytes(b"%PDF fake")
    record = _make_inventory_record("Broken.pdf", ".pdf", size_bytes=f.stat().st_size)
    run_dir = tmp_path / "run_fail"
    run_dir.mkdir()
    cfg = load_runtime_config()

    bad_response = _fake_converse_response("NOT JSON AT ALL")

    mock_client = MagicMock()
    mock_client.converse.return_value = bad_response

    with patch("proposal_ingest.analyzer.create_bedrock_runtime_client", return_value=mock_client):
        result = process_single_file(
            file_path=f,
            record=record,
            run_dir=run_dir,
            run_id="run_fail_001",
            config=cfg,
            use_mock=False,
            save_raw_responses=False,
        )

    assert result.success is False
    failure_file = run_dir / "document_metadata" / "failures" / f"{record.document_id}.json"
    assert failure_file.exists()


def test_process_single_file_bedrock_exception_saves_failure(tmp_path: Path) -> None:
    """A Bedrock API exception should save a failure record without raising."""
    f = tmp_path / "Error.pdf"
    f.write_bytes(b"%PDF fake")
    record = _make_inventory_record("Error.pdf", ".pdf", size_bytes=f.stat().st_size)
    run_dir = tmp_path / "run_exception"
    run_dir.mkdir()
    cfg = load_runtime_config()

    mock_client = MagicMock()
    mock_client.converse.side_effect = RuntimeError("simulated Bedrock error")

    with patch("proposal_ingest.analyzer.create_bedrock_runtime_client", return_value=mock_client):
        result = process_single_file(
            file_path=f,
            record=record,
            run_dir=run_dir,
            run_id="run_exc_001",
            config=cfg,
            use_mock=False,
            save_raw_responses=False,
        )

    assert result.success is False
    assert "simulated Bedrock error" in (result.error_message or "")
    failure_file = run_dir / "document_metadata" / "failures" / f"{record.document_id}.json"
    assert failure_file.exists()


# ---------------------------------------------------------------------------
# analyze_inventory — batch behavior
# ---------------------------------------------------------------------------


def test_analyze_inventory_mock_writes_usage_and_respects_limit(tmp_path: Path) -> None:
    from proposal_ingest.analyzer import analyze_inventory

    records = [
        _make_inventory_record("Technical Volume.pdf", ".pdf"),
        _make_inventory_record("Support Letter.docx", ".docx"),
    ]
    for record in records:
        file_path = tmp_path / record.file_name_original
        file_path.write_bytes(b"fake content")
        record.source_path = str(file_path)  # type: ignore[misc]
        record.size_bytes = file_path.stat().st_size  # type: ignore[misc]
    run_dir = tmp_path / "run_batch"
    run_dir.mkdir()

    results = analyze_inventory(
        run_dir,
        records,
        "run_batch",
        use_mock=True,
        config=load_runtime_config(),
        limit=1,
    )

    assert len(results) == 1
    usage_lines = (
        (run_dir / "usage" / "bedrock_usage.jsonl").read_text(encoding="utf-8").splitlines()
    )
    assert len(usage_lines) == 2
    assert json.loads(usage_lines[0])["success"] is True


def test_analyze_inventory_skips_existing_hash_unless_forced(tmp_path: Path) -> None:
    from proposal_ingest.analyzer import analyze_inventory

    record = _make_inventory_record("Technical Volume.pdf", ".pdf")
    file_path = tmp_path / record.file_name_original
    file_path.write_bytes(b"fake content")
    record.source_path = str(file_path)  # type: ignore[misc]
    record.size_bytes = file_path.stat().st_size  # type: ignore[misc]
    run_dir = tmp_path / "run_batch_skip"
    run_dir.mkdir()
    cfg = load_runtime_config()

    first = analyze_inventory(run_dir, [record], "run_batch_skip", use_mock=True, config=cfg)
    second = analyze_inventory(run_dir, [record], "run_batch_skip", use_mock=True, config=cfg)
    forced = analyze_inventory(
        run_dir, [record], "run_batch_skip", use_mock=True, config=cfg, force=True
    )

    assert len(first) == 1
    assert second == []
    assert len(forced) == 1

    jsonl_path = run_dir / "document_metadata" / "all_document_metadata.jsonl"
    lines = [line for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["document_id"] == record.document_id


def test_analyze_inventory_runs_pass2_for_ambiguous_mock_letter(tmp_path: Path) -> None:
    from proposal_ingest.analyzer import analyze_inventory
    from proposal_ingest.mock_bedrock import analyze_document_mock

    technical = _make_inventory_record("Technical Volume FINAL.docx", ".docx")
    letter = _make_inventory_record("Support Letter.docx", ".docx")
    for record in (technical, letter):
        record.proposal_id = "prop_2025-branch__abcd1234"  # type: ignore[misc]
        record.proposal_branch = "2025 Fake DOE SBIR Battery Project"  # type: ignore[misc]
        file_path = tmp_path / record.file_name_original
        file_path.write_text(record.file_name_original, encoding="utf-8")
        record.source_path = str(file_path)  # type: ignore[misc]
        record.size_bytes = file_path.stat().st_size  # type: ignore[misc]

    def ambiguous_mock(record: InventoryRecord, run_id: str) -> DocumentMetadata:
        metadata = analyze_document_mock(record, run_id)
        if record.file_name_original == "Support Letter.docx":
            metadata.document_identity.document_category = DocumentCategory.unknown
            metadata.document_identity.document_role = DocumentRole.unknown
            metadata.document_identity.origin_type = OriginType.unknown
            metadata.confidence.document_category = 0.2
            metadata.confidence.document_role = 0.2
            metadata.confidence.origin_type = 0.2
            metadata.confidence.include_in_future_rag = 0.2
        return metadata

    with patch("proposal_ingest.analyzer.analyze_document_mock", side_effect=ambiguous_mock):
        results = analyze_inventory(
            tmp_path / "run_pass2_batch",
            [technical, letter],
            "run_pass2_batch",
            use_mock=True,
            config=load_runtime_config(),
        )

    support_letter = next(
        result for result in results if result.system.file_name_original == "Support Letter.docx"
    )
    assert support_letter.system.processing_status == ProcessingStatus.processed_pass2
    assert support_letter.document_identity.document_category == DocumentCategory.partner_document
    assert support_letter.document_identity.document_role == DocumentRole.letter_of_support
    assert (tmp_path / "run_pass2_batch" / "reports" / "pass2_changes.csv").exists()
