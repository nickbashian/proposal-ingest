"""Minimal bootstrap tests: verify the CLI imports and all placeholder commands run."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

import proposal_ingest.cli
from proposal_ingest.bedrock_client import BedrockSmokeTestResult
from proposal_ingest.cli import app

runner = CliRunner()


def test_cli_imports() -> None:
    """The CLI module should import without errors."""
    assert proposal_ingest.cli.app is app


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


def test_scan_placeholder(tmp_path: Path) -> None:
    """The scan command should report a successful scan for a non-empty branch."""
    source_root = tmp_path / "source"
    output_root = tmp_path / "output"
    proposal_branch = source_root / "2025" / "Demo Proposal"
    proposal_branch.mkdir(parents=True)
    (proposal_branch / "Technical Volume.pdf").write_text("pdf content", encoding="utf-8")

    result = runner.invoke(
        app,
        ["scan", "--source-root", str(source_root), "--output-root", str(output_root)],
    )

    assert result.exit_code == 0
    assert "Scan complete:" in result.output
    assert "Inventory CSV:" in result.output


def test_scan_creates_run_directory(tmp_path: Path) -> None:
    """A non-empty scan should leave a run directory under output_root/logs."""
    source_root = tmp_path / "source"
    output_root = tmp_path / "output"
    proposal_branch = source_root / "2025" / "Demo Proposal"
    proposal_branch.mkdir(parents=True)
    (proposal_branch / "Technical Volume.pdf").write_text("pdf content", encoding="utf-8")

    result = runner.invoke(
        app,
        ["scan", "--source-root", str(source_root), "--output-root", str(output_root)],
    )

    assert result.exit_code == 0
    run_directories = list((output_root / "logs").glob("run_*"))
    assert len(run_directories) == 1
    assert (run_directories[0] / "inventory" / "file_inventory.csv").exists()


def test_scan_dry_run_does_not_create_logs(tmp_path: Path) -> None:
    """The dry-run flag should skip all filesystem writes."""
    source_root = tmp_path / "source"
    output_root = tmp_path / "output"
    proposal_branch = source_root / "2025" / "Demo Proposal"
    proposal_branch.mkdir(parents=True)
    (proposal_branch / "Technical Volume.pdf").write_text("pdf content", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "scan",
            "--source-root",
            str(source_root),
            "--output-root",
            str(output_root),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert "Dry run only." in result.output
    assert not (output_root / "logs").exists()


def test_scan_prunes_empty_run_directory(tmp_path: Path) -> None:
    """Empty scans should be pruned by default from the CLI."""
    source_root = tmp_path / "source"
    output_root = tmp_path / "output"
    (source_root / "2025").mkdir(parents=True)

    result = runner.invoke(
        app,
        [
            "scan",
            "--source-root",
            str(source_root),
            "--output-root",
            str(output_root),
        ],
    )

    assert result.exit_code == 0
    assert "Run directory pruned as empty:" in result.output
    assert not list((output_root / "logs").glob("run_*"))


def test_scan_keep_empty_runs_retains_directory(tmp_path: Path) -> None:
    """The keep-empty-runs flag should retain an otherwise empty run directory."""
    source_root = tmp_path / "source"
    output_root = tmp_path / "output"
    (source_root / "2025").mkdir(parents=True)

    result = runner.invoke(
        app,
        [
            "scan",
            "--source-root",
            str(source_root),
            "--output-root",
            str(output_root),
            "--keep-empty-runs",
        ],
    )

    assert result.exit_code == 0
    assert "Run directory:" in result.output
    assert len(list((output_root / "logs").glob("run_*"))) == 1


def test_analyze_without_mock_bedrock_exits_nonzero() -> None:
    """analyze without --mock-bedrock must fail because real Bedrock is not yet wired."""
    result = runner.invoke(app, ["analyze", "--output-root", "."])
    assert result.exit_code != 0


def test_run_all_without_mock_bedrock_exits_nonzero() -> None:
    """run-all without --mock-bedrock must fail because real Bedrock is not yet wired."""
    result = runner.invoke(app, ["run-all", "--source-root", ".", "--output-root", "."])
    assert result.exit_code != 0


def test_process_file_without_mock_bedrock_exits_nonzero() -> None:
    """process-file without --mock-bedrock must fail because real Bedrock is not yet wired."""
    result = runner.invoke(app, ["process-file", "--file", "fake.pdf", "--output-root", "."])
    assert result.exit_code != 0


def test_bedrock_smoke_test_prints_result(monkeypatch) -> None:
    """The smoke test should print the selected model, region, and response."""

    class _Config:
        class app:
            log_level = "INFO"

    monkeypatch.setattr(
        proposal_ingest.cli, "load_runtime_config", lambda *_args, **_kwargs: _Config()
    )
    monkeypatch.setattr(proposal_ingest.cli, "configure_logging", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        proposal_ingest.cli,
        "smoke_test_bedrock",
        lambda *_args, **_kwargs: BedrockSmokeTestResult(
            model_id="us.anthropic.claude-opus-4-6-v1",
            model_label="opus-4.6",
            region="us-east-1",
            response_text="Bedrock connectivity is working.",
            input_tokens=12,
            output_tokens=7,
            total_tokens=19,
        ),
    )

    result = runner.invoke(app, ["bedrock-smoke-test"])
    assert result.exit_code == 0
    assert "Model ID: us.anthropic.claude-opus-4-6-v1" in result.output
    assert "Region: us-east-1" in result.output
    assert "Response: Bedrock connectivity is working." in result.output
    assert "Usage: input=12 output=7 total=19" in result.output


def test_bedrock_smoke_test_failure_exits_with_code_4(monkeypatch) -> None:
    """Bedrock call failures should map to the documented smoke-test exit code."""

    class _Config:
        class app:
            log_level = "INFO"

    monkeypatch.setattr(
        proposal_ingest.cli, "load_runtime_config", lambda *_args, **_kwargs: _Config()
    )
    monkeypatch.setattr(proposal_ingest.cli, "configure_logging", lambda *_args, **_kwargs: None)

    def _raise(*_args, **_kwargs):
        raise RuntimeError("access denied")

    monkeypatch.setattr(proposal_ingest.cli, "smoke_test_bedrock", _raise)

    result = runner.invoke(app, ["bedrock-smoke-test"])
    assert result.exit_code == 4
    assert "Bedrock smoke test failed: access denied" in result.output
