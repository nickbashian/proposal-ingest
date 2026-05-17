"""proposal-ingest CLI entry point.

All commands are placeholders. Implement each module in the order defined in
docs/10_implementation_plan.md, then wire the real logic here.
"""

from __future__ import annotations

import typer
from rich.console import Console

app = typer.Typer(
    name="proposal-ingest",
    help="Local-first proposal archive ingestion and metadata pipeline.",
    add_completion=False,
)
console = Console()


@app.command()
def scan(
    source_root: str = typer.Option(
        ..., "--source-root", help="Path to the read-only source document root."
    ),
    output_root: str = typer.Option(..., "--output-root", help="Path to the output directory."),
    config: str | None = typer.Option(None, "--config", help="Path to a YAML config file."),
) -> None:
    """Scan the source root and generate a file inventory."""
    console.print("[yellow]scan: not yet implemented[/yellow]")
    console.print(f"  source_root = {source_root}")
    console.print(f"  output_root = {output_root}")


@app.command()
def analyze(
    output_root: str = typer.Option(..., "--output-root", help="Path to the output directory."),
    mock_bedrock: bool = typer.Option(
        False, "--mock-bedrock", help="Use mock Bedrock instead of real AWS calls."
    ),
    config: str | None = typer.Option(None, "--config", help="Path to a YAML config file."),
) -> None:
    """Analyze inventoried documents with Bedrock (or mock mode)."""
    console.print("[yellow]analyze: not yet implemented[/yellow]")
    console.print(f"  output_root  = {output_root}")
    console.print(f"  mock_bedrock = {mock_bedrock}")


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
    console.print("[yellow]run-all: not yet implemented[/yellow]")
    console.print(f"  source_root  = {source_root}")
    console.print(f"  output_root  = {output_root}")
    console.print(f"  mock_bedrock = {mock_bedrock}")


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
    console.print("[yellow]process-file: not yet implemented[/yellow]")
    console.print(f"  file               = {file}")
    console.print(f"  output_root        = {output_root}")
    console.print(f"  mock_bedrock       = {mock_bedrock}")
    console.print(f"  save_raw_responses = {save_raw_responses}")


@app.command(name="bedrock-smoke-test")
def bedrock_smoke_test() -> None:
    """Run a minimal Bedrock connectivity and authentication smoke test."""
    console.print("[yellow]bedrock-smoke-test: not yet implemented[/yellow]")


if __name__ == "__main__":
    app()
