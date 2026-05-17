"""Minimal bootstrap tests: verify the CLI imports and all placeholder commands run."""

from __future__ import annotations

from typer.testing import CliRunner

from proposal_ingest.cli import app

runner = CliRunner()


def test_cli_imports() -> None:
    """The CLI module should import without errors."""
    import proposal_ingest.cli  # noqa: F401


def test_help_exits_zero() -> None:
    """proposal-ingest --help should exit 0."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0


def test_help_lists_commands() -> None:
    """--help output should mention the key commands."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    output = result.output
    for command in ["scan", "analyze", "run-all"]:
        assert command in output, f"Expected '{command}' in --help output"


def test_scan_placeholder() -> None:
    result = runner.invoke(app, ["scan", "--source-root", ".", "--output-root", "."])
    assert result.exit_code == 0
    assert "not yet implemented" in result.output


def test_analyze_placeholder() -> None:
    result = runner.invoke(app, ["analyze", "--output-root", "."])
    assert result.exit_code == 0
    assert "not yet implemented" in result.output


def test_run_all_placeholder() -> None:
    result = runner.invoke(app, ["run-all", "--source-root", ".", "--output-root", "."])
    assert result.exit_code == 0
    assert "not yet implemented" in result.output


def test_process_file_placeholder() -> None:
    result = runner.invoke(app, ["process-file", "--file", "fake.pdf", "--output-root", "."])
    assert result.exit_code == 0
    assert "not yet implemented" in result.output


def test_bedrock_smoke_test_placeholder() -> None:
    result = runner.invoke(app, ["bedrock-smoke-test"])
    assert result.exit_code == 0
    assert "not yet implemented" in result.output
