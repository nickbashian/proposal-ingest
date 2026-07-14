"""proposal-ingest CLI entry point."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from proposal_ingest.analyzer import (
    analyze_from_output_root,
    analyze_inventory,
    analyze_inventory_with_summary,
    find_latest_inventory_jsonl,
    load_inventory_jsonl,
    process_single_file,
    summarize_analysis_resume,
)
from proposal_ingest.bedrock_client import BedrockSmokeTestResult, smoke_test_bedrock
from proposal_ingest.clean_set_builder import (
    CleanSetBlockedError,
    build_clean_set as build_clean_set_outputs,
)
from proposal_ingest.config import load_runtime_config
from proposal_ingest.file_filters import classify_path
from proposal_ingest.hashing import document_id_from_sha256, sha256_file
from proposal_ingest.logging_utils import configure_logging
from proposal_ingest.metadata_store import MetadataStore
from proposal_ingest.question_gui import launch_questions_gui
from proposal_ingest.question_loop import apply_answers_from_csv, export_questions_to_csv
from proposal_ingest.path_utils import proposal_id_from_branch, sanitize_filename
from proposal_ingest.scanner import scan_proposal_branch, scan_source_root
from proposal_ingest.schemas import APP_SCHEMA_VERSION, InventoryRecord, RunManifest

app = typer.Typer(
    name="proposal-ingest",
    help="Local-first proposal archive ingestion and metadata pipeline.",
    add_completion=False,
)
console = Console()


def _build_run_id() -> str:
    """Return a run identifier for one-off CLI operations."""
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return f"run_{timestamp}_{secrets.token_hex(3)}"


def _latest_run_dir_or_exit(output_root: str) -> Path:
    """Return the most recent run_* directory under output_root, or exit(1)."""
    logs_dir = Path(output_root) / "logs"
    run_dirs = sorted(logs_dir.glob("run_*")) if logs_dir.is_dir() else []
    if not run_dirs:
        console.print(f"[red]No run directories found under {logs_dir}[/red]")
        raise typer.Exit(code=1)
    return run_dirs[-1]


def _load_tracker_rows_for_run(run_dir: Path, tracker_path: str | None, loader: Any) -> Any:
    """Load tracker rows from an explicit path, or the run's default tracker JSONL."""
    if tracker_path:
        return loader(Path(tracker_path))
    default_tracker = run_dir / "tracker" / "tracker_rows.jsonl"
    if default_tracker.exists():
        return loader(default_tracker)
    return None


def _build_single_file_inventory_record(file_path: Path) -> InventoryRecord:
    """Build a minimal inventory record for process-file mock mode."""
    sha256_hex = sha256_file(file_path)
    classification = classify_path(file_path)
    file_stat = file_path.stat()
    proposal_id = proposal_id_from_branch(
        year_folder="unknown",
        proposal_branch_name=file_path.parent.name,
        relative_branch_path=file_path.parent.name,
    )

    return InventoryRecord(
        document_id=document_id_from_sha256(sha256_hex),
        proposal_id=proposal_id,
        source_path=str(file_path),
        relative_path=file_path.name,
        year_folder="unknown",
        proposal_branch=file_path.parent.name,
        file_name_original=file_path.name,
        file_name_safe=sanitize_filename(file_path.name),
        extension=file_path.suffix.lower(),
        size_bytes=file_stat.st_size,
        modified_time=datetime.fromtimestamp(file_stat.st_mtime, tz=UTC).isoformat(),
        sha256=sha256_hex,
        eligible_for_processing=classification.eligible_for_processing,
        processing_strategy=classification.processing_strategy,  # type: ignore[arg-type]
        processing_status=classification.processing_status,  # type: ignore[arg-type]
        skip_reason=classification.skip_reason,
    )


@app.command()
def scan(
    source_root: str = typer.Option(
        ..., "--source-root", help="Path to the read-only source document root."
    ),
    output_root: str = typer.Option(..., "--output-root", help="Path to the output directory."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview scan results without writing a run directory."
    ),
    prune_empty_runs: bool = typer.Option(
        True,
        "--prune-empty-runs/--keep-empty-runs",
        help="Prune empty run directories under output_root/logs after the scan.",
    ),
    tracker_path: str | None = typer.Option(
        None,
        "--tracker-path",
        help="Path to a grants tracker workbook (.xlsx) for normalization and later matching.",
    ),
    tracker_sheet_name: str | None = typer.Option(
        None, "--tracker-sheet-name", help="Optional tracker workbook sheet name."
    ),
    tracker_header_row: int | None = typer.Option(
        None,
        "--tracker-header-row",
        min=0,
        help="Zero-based header row index in the tracker sheet.",
    ),
    config: str | None = typer.Option(None, "--config", help="Path to a YAML config file."),
) -> None:
    """Scan the source root and generate a file inventory."""
    tracker_overrides: dict[str, object] = {}
    if tracker_path is not None:
        tracker_overrides["path"] = tracker_path
    if tracker_sheet_name is not None:
        tracker_overrides["sheet_name"] = tracker_sheet_name
    if tracker_header_row is not None:
        tracker_overrides["header_row"] = tracker_header_row
    runtime_cfg = load_runtime_config(
        config,
        overrides={
            "app": {"source_root": source_root, "output_root": output_root},
            "tracker": tracker_overrides,
        },
    )
    effective_tracker_path = runtime_cfg.tracker.path if runtime_cfg.tracker.enabled else None
    artifacts = scan_source_root(
        source_root=Path(source_root),
        output_root=Path(output_root),
        dry_run=dry_run,
        prune_empty_runs=prune_empty_runs,
        tracker_path=Path(effective_tracker_path) if effective_tracker_path else None,
        tracker_sheet_name=runtime_cfg.tracker.sheet_name,
        tracker_header_row=runtime_cfg.tracker.header_row,
    )
    console.print(f"Scan complete: {len(artifacts.inventory_records)} files inventoried")
    if effective_tracker_path and not dry_run:
        if artifacts.tracker_load_error:
            console.print(f"[yellow]Tracker ingest error: {artifacts.tracker_load_error}[/yellow]")
        else:
            console.print(f"Tracker rows loaded: {artifacts.tracker_row_count}")
            console.print(f"Tracker JSONL: {artifacts.tracker_rows_jsonl}")
    if dry_run:
        console.print(f"Dry run only. No files were written to {artifacts.run_dir}")
    elif artifacts.pruned_run_dir:
        console.print(f"Run directory pruned as empty: {artifacts.run_dir}")
    else:
        console.print(f"Run directory: {artifacts.run_dir}")
        console.print(f"Inventory CSV: {artifacts.inventory_csv}")


@app.command()
def analyze(
    output_root: str = typer.Option(..., "--output-root", help="Path to the output directory."),
    mock_bedrock: bool = typer.Option(
        False, "--mock-bedrock", help="Use mock Bedrock instead of real AWS calls."
    ),
    force: bool = typer.Option(
        False, "--force", help="Reprocess files even when hash metadata already exists."
    ),
    limit: int | None = typer.Option(
        None, "--limit", min=1, help="Process at most this many eligible files."
    ),
    save_raw_responses: bool = typer.Option(
        False, "--save-raw-responses", help="Save raw model responses to disk."
    ),
    config: str | None = typer.Option(None, "--config", help="Path to a YAML config file."),
) -> None:
    """Analyze inventoried documents with Bedrock (or mock mode)."""
    try:
        runtime_cfg = load_runtime_config(
            config,
            overrides={"bedrock": {"mock_bedrock": mock_bedrock}},
        )
        run_dir, results = analyze_from_output_root(
            Path(output_root),
            use_mock=mock_bedrock,
            config=runtime_cfg,
            force=force,
            limit=limit,
            save_raw_responses=save_raw_responses,
        )
    except FileNotFoundError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(
        f"Analyze complete: {len(results)} documents processed"
        f"{' (mock mode)' if mock_bedrock else ''}"
    )
    console.print(f"  run_dir = {run_dir}")


@app.command(name="resume-analysis")
def resume_analysis(
    output_root: str = typer.Option(..., "--output-root", help="Path to the output directory."),
    run_dir: str | None = typer.Option(
        None,
        "--run-dir",
        help="Specific run directory to resume. Defaults to the latest inventory under output_root.",
    ),
    mock_bedrock: bool = typer.Option(
        False, "--mock-bedrock", help="Use mock Bedrock instead of real AWS calls."
    ),
    limit: int | None = typer.Option(
        None, "--limit", min=1, help="Process at most this many pending eligible files."
    ),
    save_raw_responses: bool = typer.Option(
        False, "--save-raw-responses", help="Save raw model responses to disk."
    ),
    skip_pass2: bool = typer.Option(
        False,
        "--skip-pass2",
        help="Resume Pass 1 only; leave contextual Pass 2 for a later analyze/resume run.",
    ),
    config: str | None = typer.Option(None, "--config", help="Path to a YAML config file."),
) -> None:
    """Resume analysis for a partially completed run without reprocessing completed documents."""
    try:
        if run_dir is not None:
            selected_run_dir = Path(run_dir)
        else:
            inventory_path = find_latest_inventory_jsonl(Path(output_root))
            if inventory_path is None:
                raise FileNotFoundError(
                    f"No file_inventory.jsonl found under {Path(output_root) / 'logs'}."
                )
            selected_run_dir = inventory_path.parent.parent

        before = summarize_analysis_resume(selected_run_dir)
        runtime_cfg = load_runtime_config(
            config,
            overrides={"bedrock": {"mock_bedrock": mock_bedrock}},
        )
        if skip_pass2:
            runtime_cfg.processing.pass2_enabled = False
        records = load_inventory_jsonl(before.inventory_path)
        result = analyze_inventory_with_summary(
            selected_run_dir,
            records,
            selected_run_dir.name,
            use_mock=mock_bedrock,
            config=runtime_cfg,
            force=False,
            limit=limit,
            save_raw_responses=save_raw_responses,
            final_command="resume-analysis",
        )
        after = summarize_analysis_resume(selected_run_dir)
    except FileNotFoundError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(
        "Resume analysis: "
        f"{before.processed_count}/{before.eligible_count} eligible already complete, "
        f"{before.pending_count} pending"
    )
    if before.failed_pending_count:
        console.print(f"  retrying {before.failed_pending_count} previously failed pending docs")
    console.print(
        f"Attempted {result.attempted_count}, processed {len(result.documents)}, "
        f"failed {result.failed_count}, skipped {result.skipped_existing_count}"
    )
    console.print(
        f"After resume: {after.processed_count}/{after.eligible_count} eligible complete, "
        f"{after.pending_count} pending"
    )
    console.print(f"  run_dir = {selected_run_dir}")
    if result.halted_reason:
        console.print(f"[yellow]Paused after Bedrock quota limit: {result.halted_reason}[/yellow]")
        raise typer.Exit(code=2)


@app.command(name="export-questions")
def export_questions(
    output_root: str = typer.Option(..., "--output-root", help="Path to the output directory."),
    include_low_priority: bool = typer.Option(
        False, "--include-low-priority", help="Include low-priority questions in the export."
    ),
    config: str | None = typer.Option(None, "--config", help="Path to a YAML config file."),
) -> None:
    """Export the questions-to-answer CSV for human review."""
    load_runtime_config(config)  # Validates --config; this command has no other use for it.
    result = export_questions_to_csv(
        Path(output_root),
        include_low_priority=include_low_priority,
    )
    console.print(f"Exported {result.exported_count} questions to {result.questions_csv}")
    if result.suppressed_count:
        console.print(f"Suppressed {result.suppressed_count} low-priority questions")


@app.command(name="answer-questions")
def answer_questions(
    output_root: str = typer.Option(..., "--output-root", help="Path to the output directory."),
    questions_csv: str | None = typer.Option(
        None,
        "--questions-csv",
        help="Path to the questions CSV. Defaults to output_root/review/questions_to_answer.csv.",
    ),
) -> None:
    """Open a simple GUI for answering one review CSV row at a time."""
    csv_path = (
        Path(questions_csv)
        if questions_csv
        else Path(output_root) / "review" / "questions_to_answer.csv"
    )
    if not csv_path.exists():
        console.print(f"[red]Error: questions CSV not found: {csv_path}[/red]")
        raise typer.Exit(code=1)
    try:
        launch_questions_gui(csv_path)
    except ImportError as exc:
        console.print("[red]Error: Tkinter is not available in this Python environment.[/red]")
        raise typer.Exit(code=1) from exc
    except RuntimeError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"Saved answers to {csv_path}")


@app.command(name="apply-answers")
def apply_answers(
    output_root: str = typer.Option(..., "--output-root", help="Path to the output directory."),
    answers_csv: str | None = typer.Option(
        None,
        "--answers-csv",
        "--questions-csv",
        help="Path to the answered questions CSV.",
    ),
) -> None:
    """Apply human answers from the review CSV to the metadata store."""
    csv_path = (
        Path(answers_csv)
        if answers_csv
        else Path(output_root) / "review" / "questions_to_answer.csv"
    )
    result = apply_answers_from_csv(Path(output_root), csv_path)
    console.print(
        f"Applied {result.applied_count} answers; "
        f"{result.invalid_count} invalid; {result.skipped_count} skipped"
    )
    console.print(f"  archive = {result.archive_csv}")
    console.print(f"  errors  = {result.errors_csv}")


@app.command(name="synthesize-proposals")
def synthesize_proposals(
    output_root: str = typer.Option(..., "--output-root", help="Path to the output directory."),
    mock_bedrock: bool = typer.Option(
        False,
        "--mock-bedrock",
        help="Use deterministic synthesis instead of a Bedrock proposal-synthesis call.",
    ),
    tracker_path: str | None = typer.Option(
        None,
        "--tracker-path",
        help="Path to tracker JSONL file. Defaults to the tracker JSONL in the latest run dir.",
    ),
    config: str | None = typer.Option(None, "--config", help="Path to a YAML config file."),
) -> None:
    """Synthesize canonical proposal-level metadata records from document metadata."""
    from proposal_ingest.proposal_synthesizer import synthesize_all_proposals
    from proposal_ingest.tracker import load_tracker_rows_jsonl

    run_dir = _latest_run_dir_or_exit(output_root)
    store = MetadataStore(run_dir)
    runtime_cfg = load_runtime_config(config)
    tracker_rows = _load_tracker_rows_for_run(run_dir, tracker_path, load_tracker_rows_jsonl)

    results = synthesize_all_proposals(
        store,
        tracker_rows=tracker_rows,
        use_mock=mock_bedrock,
        config=runtime_cfg,
    )

    console.print(
        f"synthesize-proposals complete: {len(results)} proposal(s) synthesized"
        f"{' (mock mode)' if mock_bedrock else ''}"
    )
    for result in results:
        console.print(
            f"  {result.proposal_id}: {result.json_path} (source={result.metadata.synthesis_source})"
        )


@app.command(name="build-folders")
def build_folders(
    output_root: str = typer.Option(..., "--output-root", help="Path to the output directory."),
    mock_bedrock: bool = typer.Option(
        False,
        "--mock-bedrock",
        help="Use template-based folder summaries instead of Bedrock.",
    ),
    tracker_path: str | None = typer.Option(
        None,
        "--tracker-path",
        help="Path to tracker JSONL file. Defaults to the tracker JSONL in the latest run dir.",
    ),
    config: str | None = typer.Option(None, "--config", help="Path to a YAML config file."),
) -> None:
    """Synthesize folder-level metadata and Markdown summaries."""
    from proposal_ingest.folder_builder import build_all_folders
    from proposal_ingest.tracker import load_tracker_rows_jsonl

    run_dir = _latest_run_dir_or_exit(output_root)
    store = MetadataStore(run_dir)
    runtime_cfg = load_runtime_config(config)
    tracker_rows = _load_tracker_rows_for_run(run_dir, tracker_path, load_tracker_rows_jsonl)
    proposal_metadata_by_id = store.load_proposal_metadata_by_id()

    results = build_all_folders(
        store,
        tracker_rows=tracker_rows,
        proposal_metadata_by_id=proposal_metadata_by_id,
        use_mock=mock_bedrock,
        config=runtime_cfg,
    )

    console.print(
        f"build-folders complete: {len(results)} folder(s) synthesized"
        f"{' (mock mode)' if mock_bedrock else ''}"
    )
    for result in results:
        console.print(f"  {result.proposal_id}: {result.json_path}")


@app.command(name="build-clean-set")
def build_clean_set(
    output_root: str = typer.Option(..., "--output-root", help="Path to the output directory."),
    allow_critical_open: bool = typer.Option(
        False,
        "--allow-critical-open",
        help="Build the clean set even when critical review questions remain open.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Plan the clean set without copying files or writing manifests."
    ),
    force: bool = typer.Option(
        False, "--force", help="Rebuild generated clean-set directories for the latest run."
    ),
    allow_manual_review: bool = typer.Option(
        False,
        "--allow-manual-review",
        help="Copy included files even if manual_review_required is true.",
    ),
    config: str | None = typer.Option(None, "--config", help="Path to a YAML config file."),
) -> None:
    """Build the clean mirrored document output and S3 manifest."""
    runtime_cfg = load_runtime_config(config)
    try:
        result = build_clean_set_outputs(
            Path(output_root),
            allow_critical_open=allow_critical_open,
            dry_run=dry_run,
            force=force,
            sanitize_filenames=runtime_cfg.clean_set.sanitize_filenames,
            flatten_documents_folder=runtime_cfg.clean_set.flatten_documents_folder,
            require_manual_review_clearance=(
                runtime_cfg.clean_set.require_manual_review_clearance and not allow_manual_review
            ),
            s3_manifest_enabled=runtime_cfg.s3_manifest.enabled,
            s3_base_prefix=runtime_cfg.s3_manifest.base_prefix,
        )
    except CleanSetBlockedError as exc:
        console.print(f"[red]{exc}[/red]")
        for question in exc.questions[:10]:
            console.print(
                "  "
                f"{question.get('question_id')}: "
                f"{question.get('file_name_original') or question.get('document_id')} "
                f"{question.get('field')}"
            )
        raise typer.Exit(code=3) from exc
    except FileNotFoundError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    label = "build-clean-set dry run" if dry_run else "build-clean-set complete"
    console.print(
        f"{label}: {result.copied_count} copied, "
        f"{result.excluded_count} excluded, {result.manifest_count} manifest rows"
    )
    console.print(f"  run_dir = {result.run_dir}")
    console.print(f"  excluded = {result.excluded_report_path}")
    console.print(f"  manifest = {result.manifest_path}")


@app.command(name="run-all")
def run_all(
    source_root: str = typer.Option(
        ..., "--source-root", help="Path to the read-only source document root."
    ),
    output_root: str = typer.Option(..., "--output-root", help="Path to the output directory."),
    mock_bedrock: bool = typer.Option(
        False, "--mock-bedrock", help="Use mock Bedrock instead of real AWS calls."
    ),
    config: str | None = typer.Option(None, "--config", help="Path to a YAML config file."),
) -> None:
    """Run the implemented pipeline end-to-end through clean-set output."""
    from proposal_ingest.folder_builder import build_all_folders
    from proposal_ingest.proposal_synthesizer import synthesize_all_proposals
    from proposal_ingest.tracker import load_tracker_rows_jsonl

    runtime_cfg = load_runtime_config(
        config,
        overrides={
            "app": {"source_root": source_root, "output_root": output_root},
            "bedrock": {"mock_bedrock": mock_bedrock},
        },
    )
    effective_tracker_path = runtime_cfg.tracker.path if runtime_cfg.tracker.enabled else None

    # Stage 1: scan
    artifacts = scan_source_root(
        source_root=Path(source_root),
        output_root=Path(output_root),
        tracker_path=Path(effective_tracker_path) if effective_tracker_path else None,
        tracker_sheet_name=runtime_cfg.tracker.sheet_name,
        tracker_header_row=runtime_cfg.tracker.header_row,
    )
    console.print(f"Scan complete: {len(artifacts.inventory_records)} files inventoried")
    if effective_tracker_path:
        if artifacts.tracker_load_error:
            console.print(f"[yellow]Tracker ingest error: {artifacts.tracker_load_error}[/yellow]")
        else:
            console.print(f"Tracker rows loaded: {artifacts.tracker_row_count}")

    if artifacts.pruned_run_dir:
        console.print("[yellow]No eligible files found — run directory pruned.[/yellow]")
        return

    # Stage 2: analyze
    eligible = [r for r in artifacts.inventory_records if r.eligible_for_processing]
    results = analyze_inventory(
        artifacts.run_dir,
        artifacts.inventory_records,
        artifacts.run_id,
        use_mock=mock_bedrock,
        config=runtime_cfg,
        final_command="run-all",
    )
    console.print(
        f"Analyze complete: {len(results)} of {len(eligible)} eligible documents"
        f" processed{' (mock mode)' if mock_bedrock else ''}"
    )

    # Stage 3: export questions
    questions_result = export_questions_to_csv(
        Path(output_root),
        include_low_priority=False,
    )
    console.print(
        f"Exported {questions_result.exported_count} questions to "
        f"{questions_result.questions_csv}"
    )

    # Stage 4: proposal synthesis
    tracker_rows = None
    if artifacts.tracker_rows_jsonl.exists():
        tracker_rows = load_tracker_rows_jsonl(artifacts.tracker_rows_jsonl)
    store = MetadataStore(artifacts.run_dir)
    proposal_results = synthesize_all_proposals(
        store,
        tracker_rows=tracker_rows,
        use_mock=mock_bedrock,
        config=runtime_cfg,
    )
    console.print(
        f"synthesize-proposals complete: {len(proposal_results)} proposal(s) synthesized"
        f"{' (mock mode)' if mock_bedrock else ''}"
    )

    # Stage 5: folder synthesis
    proposal_metadata_by_id = {r.proposal_id: r.metadata for r in proposal_results}
    folder_results = build_all_folders(
        store,
        tracker_rows=tracker_rows,
        proposal_metadata_by_id=proposal_metadata_by_id,
        use_mock=mock_bedrock,
        config=runtime_cfg,
    )
    console.print(
        f"build-folders complete: {len(folder_results)} folder(s) synthesized"
        f"{' (mock mode)' if mock_bedrock else ''}"
    )

    # Stage 6: clean-set and S3 manifest
    try:
        clean_result = build_clean_set_outputs(
            Path(output_root),
            allow_critical_open=not runtime_cfg.processing.stop_before_clean_set_if_critical_questions,
            dry_run=False,
            force=True,
            sanitize_filenames=runtime_cfg.clean_set.sanitize_filenames,
            flatten_documents_folder=runtime_cfg.clean_set.flatten_documents_folder,
            require_manual_review_clearance=runtime_cfg.clean_set.require_manual_review_clearance,
            s3_manifest_enabled=runtime_cfg.s3_manifest.enabled,
            s3_base_prefix=runtime_cfg.s3_manifest.base_prefix,
        )
    except CleanSetBlockedError as exc:
        console.print(f"[red]{exc}[/red]")
        console.print(
            "Resolve critical questions with apply-answers or rerun with the gate disabled."
        )
        raise typer.Exit(code=3) from exc
    console.print(
        f"build-clean-set complete: {clean_result.copied_count} copied, "
        f"{clean_result.excluded_count} excluded, "
        f"{clean_result.manifest_count} manifest rows"
    )
    console.print(f"  run_dir = {artifacts.run_dir}")


@app.command(name="process-folder")
def process_folder(
    source_folder: str = typer.Option(
        ...,
        "--source-folder",
        "--folder",
        help="Path to a single proposal branch folder to process.",
    ),
    output_root: str = typer.Option(..., "--output-root", help="Path to the output directory."),
    mock_bedrock: bool = typer.Option(
        False, "--mock-bedrock", help="Use mock Bedrock instead of real AWS calls."
    ),
    config: str | None = typer.Option(None, "--config", help="Path to a YAML config file."),
) -> None:
    """Process a single proposal branch folder."""
    from proposal_ingest.folder_builder import build_all_folders
    from proposal_ingest.proposal_synthesizer import synthesize_all_proposals

    try:
        runtime_cfg = load_runtime_config(
            config,
            overrides={
                "app": {"source_root": source_folder, "output_root": output_root},
                "bedrock": {"mock_bedrock": mock_bedrock},
            },
        )
        artifacts = scan_proposal_branch(
            source_folder=Path(source_folder),
            output_root=Path(output_root),
        )
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(f"Scan complete: {len(artifacts.inventory_records)} files inventoried")
    if artifacts.pruned_run_dir:
        console.print("[yellow]No eligible files found — run directory pruned.[/yellow]")
        return

    eligible = [r for r in artifacts.inventory_records if r.eligible_for_processing]
    results = analyze_inventory(
        artifacts.run_dir,
        artifacts.inventory_records,
        artifacts.run_id,
        use_mock=mock_bedrock,
        config=runtime_cfg,
        final_command="process-folder",
    )
    console.print(
        f"Analyze complete: {len(results)} of {len(eligible)} eligible documents"
        f" processed{' (mock mode)' if mock_bedrock else ''}"
    )

    questions_result = export_questions_to_csv(
        Path(output_root),
        include_low_priority=False,
    )
    console.print(
        f"Exported {questions_result.exported_count} questions to "
        f"{questions_result.questions_csv}"
    )

    store = MetadataStore(artifacts.run_dir)
    proposal_results = synthesize_all_proposals(
        store,
        use_mock=mock_bedrock,
        config=runtime_cfg,
    )
    proposal_metadata_by_id = {r.proposal_id: r.metadata for r in proposal_results}
    folder_results = build_all_folders(
        store,
        proposal_metadata_by_id=proposal_metadata_by_id,
        use_mock=mock_bedrock,
        config=runtime_cfg,
    )
    console.print(
        f"build-folders complete: {len(folder_results)} folder(s) synthesized"
        f"{' (mock mode)' if mock_bedrock else ''}"
    )
    console.print(f"  run_dir = {artifacts.run_dir}")


@app.command(name="process-file")
def process_file(
    file: str = typer.Option(..., "--file", help="Path to a single document file to process."),
    output_root: str = typer.Option(..., "--output-root", help="Path to the output directory."),
    mock_bedrock: bool = typer.Option(
        False, "--mock-bedrock", help="Use mock Bedrock instead of real AWS calls."
    ),
    save_raw_responses: bool = typer.Option(
        False, "--save-raw-responses", help="Save raw model responses to disk."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print strategy info without making Bedrock calls or writing output.",
    ),
    config_path: str | None = typer.Option(None, "--config", help="Path to a YAML config file."),
) -> None:
    """Process a single document file with Bedrock (or mock / dry-run mode)."""
    file_path = Path(file).resolve()
    if not file_path.is_file():
        console.print(f"[red]Error: file not found: {file_path}[/red]")
        raise typer.Exit(code=1)

    runtime_cfg = load_runtime_config(
        config_path, overrides={"bedrock": {"mock_bedrock": mock_bedrock}}
    )

    run_id = _build_run_id()
    run_dir = Path(output_root).resolve() / "logs" / run_id

    if not dry_run:
        run_dir.mkdir(parents=True, exist_ok=True)

    record = _build_single_file_inventory_record(file_path)

    if dry_run:
        from proposal_ingest.analyzer import _decide_strategy

        strategy = _decide_strategy(file_path, record, runtime_cfg)
        console.print("[bold]Dry run — no Bedrock calls or output will be written.[/bold]")
        console.print(f"  file             = {file_path}")
        console.print(f"  document_id      = {record.document_id}")
        console.print(f"  extension        = {record.extension}")
        console.print(f"  size_bytes       = {record.size_bytes}")
        console.print(f"  strategy         = {strategy}")
        console.print(f"  mock_bedrock     = {mock_bedrock}")
        console.print(f"  output_run_dir   = {run_dir}  (not created)")
        return

    result = process_single_file(
        file_path=file_path,
        record=record,
        run_dir=run_dir,
        run_id=run_id,
        config=runtime_cfg,
        use_mock=mock_bedrock,
        save_raw_responses=save_raw_responses,
    )

    MetadataStore(run_dir).write_run_manifest(
        RunManifest(
            schema_version=APP_SCHEMA_VERSION,
            run_id=run_id,
            command="process-file",
            source_root=str(file_path.parent),
            output_root=str(Path(output_root).resolve()),
            config_snapshot={
                "mock_bedrock": mock_bedrock,
                "save_raw_responses": save_raw_responses,
            },
            git_commit=None,
            timestamp=datetime.now(UTC).isoformat(),
            mock_bedrock=mock_bedrock,
        )
    )

    if result.success and result.metadata:
        console.print(
            f"[green]process-file complete[/green]"
            f"{'[mock]' if mock_bedrock else ''}: {record.document_id}"
        )
    else:
        console.print(f"[red]process-file failed: {result.error_message}[/red]")
        raise typer.Exit(code=1)

    console.print(f"  run_dir = {run_dir}")


def _shorten_console_text(text: str, *, limit: int = 200) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3]}..."


@app.command(name="bedrock-smoke-test")
def bedrock_smoke_test(
    config: str | None = typer.Option(None, "--config", help="Path to a YAML config file."),
) -> None:
    """Run a minimal Bedrock connectivity and authentication smoke test."""
    try:
        runtime_config = load_runtime_config(config)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Configuration error: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    configure_logging(runtime_config.app.log_level)

    try:
        result = smoke_test_bedrock(runtime_config)
    except Exception as exc:
        console.print(f"[red]Bedrock smoke test failed: {exc}[/red]")
        raise typer.Exit(code=4) from exc

    _print_bedrock_smoke_test_result(result)


def _print_bedrock_smoke_test_result(result: BedrockSmokeTestResult) -> None:
    console.print(f"Model ID: {result.model_id}")
    console.print(f"Region: {result.region}")
    console.print(f"Response: {_shorten_console_text(result.response_text)}")
    if result.total_tokens is not None:
        console.print(
            "Usage: "
            f"input={result.input_tokens or 0} "
            f"output={result.output_tokens or 0} "
            f"total={result.total_tokens}"
        )


if __name__ == "__main__":
    app()
