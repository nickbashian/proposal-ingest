"""Fail when repository files contain likely credentials or private artifacts."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_SIZE = 2 * 1024 * 1024
FORBIDDEN_PATH_PARTS = {
    "db_dumps",
    "private_data",
    "private_evaluations",
    "private_screenshots",
    "raw_model_responses",
}
FORBIDDEN_SUFFIXES = {".tfstate", ".tfstate.backup"}

SECRET_PATTERNS = {
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
ASSIGNMENT_PATTERN = re.compile(
    r"\b[A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|CLIENT_SECRET)[A-Z0-9_]*\b"
    r"\s*[:=]\s*[\"']?([A-Za-z0-9][A-Za-z0-9+/_=.-]{5,})"
)
SAFE_ASSIGNMENT_MARKERS = (
    "${",
    "<",
    "change-me",
    "example",
    "local-development",
    "placeholder",
    "redacted",
    "********",
    "false",
    "none",
    "null",
    "true",
)


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    kind: str


def _repository_paths() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / Path(item.decode()) for item in result.stdout.split(b"\0") if item]


def _forbidden_path(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    parts = {part.casefold() for part in relative.parts}
    suffixes = "".join(relative.suffixes).casefold()
    return bool(parts & FORBIDDEN_PATH_PARTS) or suffixes in FORBIDDEN_SUFFIXES


def _is_safe_assignment(value: str) -> bool:
    normalized = value.casefold()
    return not value or any(marker in normalized for marker in SAFE_ASSIGNMENT_MARKERS)


def scan_text(path: Path, text: str) -> list[Finding]:
    """Return likely-secret findings for decoded repository text."""

    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in SECRET_PATTERNS.items():
            if pattern.search(line):
                findings.append(Finding(path, number, kind))
        assignment = ASSIGNMENT_PATTERN.search(line)
        if assignment and not _is_safe_assignment(assignment.group(1)):
            findings.append(Finding(path, number, "non-placeholder secret assignment"))
    return findings


def scan_paths(paths: Iterable[Path]) -> list[Finding]:
    """Scan repository paths without printing sensitive matched values."""

    findings: list[Finding] = []
    for path in paths:
        if not path.is_file():
            continue
        if _forbidden_path(path):
            findings.append(Finding(path, 0, "private/generated artifact path"))
            continue
        if path.stat().st_size > MAX_FILE_SIZE:
            continue
        payload = path.read_bytes()
        if b"\0" in payload:
            continue
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            continue
        findings.extend(scan_text(path, text))
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    paths = [Path(item).resolve() for item in argv] if argv else _repository_paths()
    findings = scan_paths(paths)
    if not findings:
        print(f"Secret/private-artifact scan passed ({len(paths)} files).")
        return 0
    print("Secret/private-artifact scan failed:", file=sys.stderr)
    for finding in findings:
        relative = finding.path.relative_to(ROOT)
        location = f":{finding.line}" if finding.line else ""
        print(f"  {relative}{location}: {finding.kind}", file=sys.stderr)
    print(
        "Matched values are intentionally omitted. Remove the artifact or credential.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
