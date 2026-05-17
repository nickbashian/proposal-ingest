"""proposal-ingest CLI entry point.

All commands are placeholders. Implement each module in the order defined in
docs/10_implementation_plan.md, then wire the real logic here.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console

from proposal_ingest.analyzer import analyze_from_output_root, analyze_inventory
from proposal_ingest.file_filters import classify_path
from proposal_ingest.hashing import document_id_from_sha256, sha256_file
from proposal_ingest.metadata_store import MetadataStore
from proposal_ingest.mock_bedrock import analyze_document_mock
from proposal_ingest.path_utils import proposal_id_from_branch, sanitize_filename
from proposal_ingest.scanner import scan_source_root
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
    config: str | None = typer.Option(None, "--config", help="Path to a YAML config file."),
) -> None:
    """Scan the source root and generate a file inventory."""
    del config
    artifacts = scan_source_root(
        source_root=Path(source_root),
        output_root=Path(output_root),
        dry_run=dry_run,
        prune_empty_runs=prune_empty_runs,
    )
    console.print(f"Scan complete: {len(artifacts.inventory_records)} files inventoried")
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
    config: str | None = typer.Option(None, "--config", help="Path to a YAML config file."),
) -> None:
    """Analyze inventoried documents with Bedrock (or mock mode)."""
    del config
    if not mock_bedrock:
        console.print("[red]Real Bedrock not yet implemented. Use --mock-bedrock.[/red]")
        raise typer.Exit(code=1)
    try:
        run_dir, results = analyze_from_output_root(Path(output_root), use_mock=mock_bedrock)
    except FileNotFoundError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"Analyze complete: {len(results)} documents processed (mock mode)")
    console.print(f"  run_dir = {run_dir}")


@app.command(name="export-questions")
def export_questions(
    output_root: str = typer.Option(..., "--output-root", help="Path to the output directory."),
) -> None:
    """Export the questions-to-answer CSV for human review."""
    console.print("[yellow]export-questions: not yet implemented[/yellow]")
    console.print(f"  output_root = {output_root}")


@app.command(name="apply-answers")
def apply_answers(
    output_root: str = typer.Option(..., "--output-root", help="Path to the output directory."),
    answers_csv: str = typer.Option(
        ..., "--answers-csv", help="Path to the answered questions CSV."
    ),
) -> None:
    """Apply human answers from the review CSV to the metadata store."""
    console.print("[yellow]apply-answers: not yet implemented[/yellow]")
    console.print(f"  output_root = {output_root}")
    console.print(f"  answers_csv = {answers_csv}")


@app.command(name="build-folders")
def build_folders(
    output_root: str = typer.Option(..., "--output-root", help="Path to the output directory."),
) -> None:
    """Synthesize folder-level metadata and Markdown summaries."""
    console.print("[yellow]build-folders: not yet implemented[/yellow]")
    console.print(f"  output_root = {output_root}")


@app.command(name="build-clean-set")
def build_clean_set(
    output_root: str = typer.Option(..., "--output-root", help="Path to the output directory."),
) -> None:
    """Build the clean mirrored document output and S3 manifest."""
    console.print("[yellow]build-clean-set: not yet implemented[/yellow]")
    console.print(f"  output_root = {output_root}")


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
    """Run the full pipeline end-to-end."""
    del config
    if not mock_bedrock:
        console.print("[red]Real Bedrock not yet implemented. Use --mock-bedrock.[/red]")
        raise typer.Exit(code=1)

    # Stage 1: scan
    artifacts = scan_source_root(
        source_root=Path(source_root),
        output_root=Path(output_root),
    )
    console.print(f"Scan complete: {len(artifacts.inventory_records)} files inventoried")

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
    )
    console.print(
        f"Analyze complete: {len(results)} of {len(eligible)} eligible documents"
        " processed (mock mode)"
    )
    console.print(f"  run_dir = {artifacts.run_dir}")


@app.command(name="process-folder")
def process_folder(
    folder: str = typer.Option(
        ..., "--folder", help="Path to a single proposal branch folder to process."
    ),
    output_root: str = typer.Option(..., "--output-root", help="Path to the output directory."),
    mock_bedrock: bool = typer.Option(
        False, "--mock-bedrock", help="Use mock Bedrock instead of real AWS calls."
    ),
) -> None:
    """Process a single proposal branch folder."""
    console.print("[yellow]process-folder: not yet implemented[/yellow]")
    console.print(f"  folder       = {folder}")
    console.print(f"  output_root  = {output_root}")
    console.print(f"  mock_bedrock = {mock_bedrock}")


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
) -> None:
    """Process a single document file."""
    del save_raw_responses  # real Bedrock path; reserved for Phase 6
    if not mock_bedrock:
        console.print("[red]Real Bedrock not yet implemented. Use --mock-bedrock.[/red]")
        raise typer.Exit(code=1)

    file_path = Path(file).resolve()
    if not file_path.is_file():
        console.print(f"[red]Error: file not found: {file_path}[/red]")
        raise typer.Exit(code=1)

    run_id = _build_run_id()
    run_dir = Path(output_root).resolve() / "logs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    record = _build_single_file_inventory_record(file_path)

    metadata = analyze_document_mock(record, run_id)
    MetadataStore(run_dir).write_document_metadata(metadata)
    MetadataStore(run_dir).write_run_manifest(
        RunManifest(
            schema_version=APP_SCHEMA_VERSION,
            run_id=run_id,
            command="process-file",
            source_root=str(file_path.parent),
            output_root=str(Path(output_root).resolve()),
            config_snapshot={"mock_bedrock": mock_bedrock},
            git_commit=None,
            timestamp=datetime.now(UTC).isoformat(),
            mock_bedrock=mock_bedrock,
        )
    )
    console.print(f"process-file complete (mock mode): {record.document_id}")
    console.print(f"  run_dir = {run_dir}")


@app.command(name="bedrock-smoke-test")
def bedrock_smoke_test() -> None:
    """Run a minimal Bedrock connectivity and authentication smoke test."""
    console.print("[yellow]bedrock-smoke-test: not yet implemented[/yellow]")


if __name__ == "__main__":
    app()
