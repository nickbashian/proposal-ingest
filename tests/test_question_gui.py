"""Tests for the one-question-at-a-time review CSV GUI helpers."""

from __future__ import annotations

import csv
from pathlib import Path

from typer.testing import CliRunner

import proposal_ingest.cli
from proposal_ingest.cli import app
from proposal_ingest.question_gui import (
    answer_row,
    choices_for_row,
    load_question_rows,
    skip_row,
    write_question_rows,
)
from proposal_ingest.question_loop import REVIEW_COLUMNS
from proposal_ingest.schemas import QuestionStatus

runner = CliRunner()


def _write_questions_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "question_id": "q_1",
            "run_id": "run_demo",
            "proposal_id": "prop_demo",
            "document_id": "doc_1",
            "source_path": "/source/Technical Volume.pdf",
            "proposal_branch": "Demo Proposal",
            "file_name_original": "Technical Volume.pdf",
            "field": "version_status",
            "question": "Is this the final submitted version?",
            "priority": "high",
            "suggested_options": "final | draft | unknown",
            "model_guess": "unknown",
            "user_answer": "",
            "answer_type": "enum",
            "status": "open",
            "created_at": "2026-05-17T12:00:00+00:00",
            "updated_at": "",
            "applied_at": "",
            "notes": "",
        }
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def test_question_gui_helpers_answer_and_rewrite_csv(tmp_path: Path) -> None:
    questions_csv = tmp_path / "review" / "questions_to_answer.csv"
    _write_questions_csv(questions_csv)

    rows = load_question_rows(questions_csv)
    answer_row(rows[0], "final")
    write_question_rows(questions_csv, rows)

    reloaded = load_question_rows(questions_csv)
    assert reloaded[0]["user_answer"] == "final"
    assert reloaded[0]["status"] == QuestionStatus.answered.value
    assert reloaded[0]["updated_at"]
    assert list(reloaded[0].keys()) == REVIEW_COLUMNS


def test_question_gui_helpers_parse_choices_and_boolean_defaults() -> None:
    enum_row = {"suggested_options": "final | draft | unknown", "answer_type": "enum"}
    bool_row = {"suggested_options": "", "answer_type": "boolean"}
    list_row = {"suggested_options": "public, internal", "answer_type": "list"}

    assert choices_for_row(enum_row).choices == ("final", "draft", "unknown")
    assert choices_for_row(bool_row).choices == ("true", "false")
    assert choices_for_row(list_row).allow_multiple is True


def test_question_gui_helpers_skip_row() -> None:
    row = {"status": "open", "updated_at": ""}

    skip_row(row)

    assert row["status"] == QuestionStatus.skipped.value
    assert row["updated_at"]


def test_answer_questions_cli_uses_default_csv_path(tmp_path: Path, monkeypatch) -> None:
    questions_csv = tmp_path / "review" / "questions_to_answer.csv"
    _write_questions_csv(questions_csv)
    captured: dict[str, Path] = {}

    def _fake_launch(path: Path) -> None:
        captured["path"] = path

    monkeypatch.setattr(proposal_ingest.cli, "launch_questions_gui", _fake_launch)

    result = runner.invoke(app, ["answer-questions", "--output-root", str(tmp_path)])

    assert result.exit_code == 0
    assert captured["path"] == questions_csv
    assert "Saved answers to" in result.output


def test_answer_questions_cli_reports_missing_csv(tmp_path: Path) -> None:
    result = runner.invoke(app, ["answer-questions", "--output-root", str(tmp_path)])

    assert result.exit_code == 1
    assert "questions CSV not found" in result.output
