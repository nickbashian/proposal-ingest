"""Minimal bootstrap tests: verify the CLI imports and all placeholder commands run."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

import proposal_ingest.cli
from proposal_ingest.bedrock_client import BedrockSmokeTestResult
from proposal_ingest.cli import app
from proposal_ingest.scanner import ScanArtifacts

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


def test_scan_with_tracker_path_writes_tracker_jsonl(tmp_path: Path) -> None:
    """scan --tracker-path should ingest tracker rows into the run directory."""
    source_root = tmp_path / "source"
    output_root = tmp_path / "output"
    proposal_branch = source_root / "2025" / "Demo Proposal"
    proposal_branch.mkdir(parents=True)
    (proposal_branch / "Technical Volume.pdf").write_text("pdf content", encoding="utf-8")

    tracker_path = tmp_path / "tracker.xlsx"
    pd.DataFrame(
        [{"proposal_name": "Demo Proposal", "status": "submitted", "award_status": "unknown"}]
    ).to_excel(tracker_path, index=False)

    result = runner.invoke(
        app,
        [
            "scan",
            "--source-root",
            str(source_root),
            "--output-root",
            str(output_root),
            "--tracker-path",
            str(tracker_path),
        ],
    )

    assert result.exit_code == 0
    assert "Tracker rows loaded: 1" in result.output
    run_directories = list((output_root / "logs").glob("run_*"))
    assert len(run_directories) == 1
    assert (run_directories[0] / "tracker" / "tracker_rows.jsonl").exists()


def test_scan_dry_run_with_tracker_path_does_not_print_tracker_loaded(tmp_path: Path) -> None:
    """scan --dry-run should not print tracker-loaded paths that are not written."""
    source_root = tmp_path / "source"
    output_root = tmp_path / "output"
    proposal_branch = source_root / "2025" / "Demo Proposal"
    proposal_branch.mkdir(parents=True)
    (proposal_branch / "Technical Volume.pdf").write_text("pdf content", encoding="utf-8")

    tracker_path = tmp_path / "tracker.xlsx"
    pd.DataFrame(
        [{"proposal_name": "Demo Proposal", "status": "submitted", "award_status": "unknown"}]
    ).to_excel(tracker_path, index=False)

    result = runner.invoke(
        app,
        [
            "scan",
            "--source-root",
            str(source_root),
            "--output-root",
            str(output_root),
            "--tracker-path",
            str(tracker_path),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "Tracker rows loaded:" not in result.output
    assert "Tracker JSONL:" not in result.output


def test_scan_respects_tracker_header_row_from_config_when_cli_not_set(
    tmp_path: Path, monkeypatch
) -> None:
    """scan should not override tracker.header_row unless --tracker-header-row is provided."""
    source_root = tmp_path / "source"
    output_root = tmp_path / "output"
    source_root.mkdir(parents=True)
    output_root.mkdir(parents=True)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "app:\n"
        "  source_root: null\n"
        "  output_root: null\n"
        "tracker:\n"
        "  enabled: true\n"
        "  path: /tmp/tracker.xlsx\n"
        "  sheet_name: Tracker\n"
        "  header_row: 3\n",
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def _fake_scan_source_root(*args, **kwargs):
        captured.update(kwargs)
        run_dir = Path(output_root) / "logs" / "run_fake"
        return ScanArtifacts(
            run_id="run_fake",
            run_dir=run_dir,
            inventory_csv=run_dir / "inventory" / "file_inventory.csv",
            inventory_jsonl=run_dir / "inventory" / "file_inventory.jsonl",
            stray_files_csv=run_dir / "inventory" / "stray_files_ignored.csv",
            powerpoint_questions_jsonl=run_dir / "inventory" / "powerpoint_review_questions.jsonl",
            run_manifest_path=run_dir / "run_manifest.json",
            wrote_outputs=False,
            pruned_run_dir=False,
            inventory_records=[],
            stray_files=[],
            powerpoint_review_questions=[],
            tracker_rows_jsonl=run_dir / "tracker" / "tracker_rows.jsonl",
            tracker_row_count=0,
            tracker_load_error=None,
        )

    monkeypatch.setattr(proposal_ingest.cli, "scan_source_root", _fake_scan_source_root)

    result = runner.invoke(
        app,
        [
            "scan",
            "--source-root",
            str(source_root),
            "--output-root",
            str(output_root),
            "--config",
            str(config_path),
        ],
    )
    assert result.exit_code == 0
    assert captured["tracker_header_row"] == 3


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
