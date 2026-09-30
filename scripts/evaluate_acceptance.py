"""Freeze and score private MVP-09/10 acceptance manifests without provider calls."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proposal_app.acceptance_harness import (  # noqa: E402
    ManifestError,
    assert_no_group_overlap,
    freeze_manifest,
    score_manifest,
    validate_manifest,
)

PRIVATE_ROOT = (ROOT / "private_evaluations").resolve()


def _private_path(raw: str | Path) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    resolved = path.resolve()
    if resolved == PRIVATE_ROOT or PRIVATE_ROOT not in resolved.parents:
        raise ManifestError("Input and report paths must stay inside ignored private_evaluations/")
    return resolved


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError("Could not read a valid JSON evaluation manifest") from exc
    if not isinstance(value, dict):
        raise ManifestError("Evaluation manifest must be a JSON object")
    return value


def _write(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ManifestError("Private output already exists; choose a new versioned path")
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".acceptance-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze", help="validate and freeze a private candidate manifest")
    freeze.add_argument("--manifest", required=True)
    freeze.add_argument("--output", required=True)
    freeze.add_argument(
        "--against",
        action="append",
        default=[],
        help="frozen suite to check for group/fingerprint overlap",
    )

    validate = commands.add_parser("validate", help="validate an existing frozen private manifest")
    validate.add_argument("--manifest", required=True)
    validate.add_argument("--against", action="append", default=[])

    score = commands.add_parser("score", help="write a private aggregate-only score report")
    score.add_argument("--manifest", required=True)
    score.add_argument("--report", required=True)
    score.add_argument("--against", action="append", default=[])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source_path = _private_path(args.manifest)
        manifest = _read(source_path)
        if args.command == "freeze":
            output_path = _private_path(args.output)
            input_paths = [source_path, *(_private_path(path) for path in args.against)]
            if output_path in input_paths:
                raise ManifestError("Freeze output must be separate from input suites")
            frozen = freeze_manifest(manifest)
            related = [_read(path) for path in input_paths[1:]]
            assert_no_group_overlap([frozen, *related])
            _write(output_path, frozen)
            print("Manifest frozen and written to private storage.")
            return 0
        validate_manifest(manifest)
        input_paths = [source_path, *(_private_path(path) for path in args.against)]
        related = [_read(path) for path in input_paths[1:]]
        assert_no_group_overlap([manifest, *related])
        if args.command == "validate":
            print("Manifest valid; split grouping has no detected overlap.")
            return 0
        report = score_manifest(manifest)
        report_path = _private_path(args.report)
        if report_path in input_paths:
            raise ManifestError("Report path must be separate from all input suites")
        _write(report_path, report)
        print(f"Acceptance status: {report['status']}. Aggregate report saved privately.")
        return {"pass": 0, "pending": 2, "fail": 1}[report["status"]]
    except ManifestError as exc:
        print(f"Evaluation stopped: {exc}", file=sys.stderr)
        return 1
    except OSError:
        print(
            "Evaluation stopped: a private input/output file could not be accessed.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
