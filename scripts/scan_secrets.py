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
FORBIDDEN_SUFFIXES = {".dump", ".sql.gz", ".tfstate", ".tfstate.backup"}
ALLOWED_BINARY_FIXTURES = {
    "sample_data/fake_source_root/2025/2025 Fake DOE SBIR Battery Project/Budget.xlsx",
    "sample_data/fake_source_root/2025/2025 Fake DOE SBIR Battery Project/FOA Instructions.pdf",
    "sample_data/fake_source_root/2025/2025 Fake DOE SBIR Battery Project/Quad Chart.pdf",
    "sample_data/fake_source_root/2025/2025 Fake DOE SBIR Battery Project/Quad Chart.pptx",
    "sample_data/fake_source_root/2025/2025 Fake DOE SBIR Battery Project/Support Letter.docx",
    "sample_data/fake_source_root/2025/2025 Fake DOE SBIR Battery Project/Technical Volume FINAL.docx",
    "sample_data/fake_source_root/General/Empower Grant Activities/Grants In Progress/fake_grants_tracker.xlsx",
}

SECRET_PATTERNS = {
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:[A-Z0-9]+_)*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|CLIENT_SECRET|ACCESS_TOKEN|AUTH_TOKEN|BEARER_TOKEN)\b"
    r"\s*[:=]\s*[\"']?([A-Za-z0-9][A-Za-z0-9+/_=.-]{5,})"
)
SAFE_ASSIGNMENT_PATTERN = re.compile(
    r"(?:\$\{[A-Z0-9_]+(?::-[^}]*)?\}|<[^>]+>|\*{6,}|"
    r"(?:change-me|example|placeholder|redacted)(?:[-_][A-Za-z0-9]+)*|"
    r"local-development-only)",
    re.IGNORECASE,
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
    name = relative.name.casefold()
    return (
        bool(parts & FORBIDDEN_PATH_PARTS)
        or name.endswith(tuple(FORBIDDEN_SUFFIXES))
        or ".tfstate." in name
    )


def _is_safe_assignment(value: str) -> bool:
    return not value or SAFE_ASSIGNMENT_PATTERN.fullmatch(value) is not None


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


def _with_line_offset(findings: Iterable[Finding], offset: int) -> list[Finding]:
    return [Finding(item.path, item.line + offset, item.kind) for item in findings]


def _scan_large_file(path: Path) -> list[Finding]:
    """Scan oversized UTF-8 text incrementally and fail closed on binary data."""

    findings: list[Finding] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if "\0" in line:
                    return [Finding(path, 0, "unallowlisted oversized binary file")]
                findings.extend(_with_line_offset(scan_text(path, line), number - 1))
    except UnicodeDecodeError:
        return [Finding(path, 0, "unallowlisted oversized non-UTF-8 file")]
    return findings


def _is_allowed_binary_fixture(path: Path) -> bool:
    return path.relative_to(ROOT).as_posix() in ALLOWED_BINARY_FIXTURES


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
            if _is_allowed_binary_fixture(path):
                continue
            findings.extend(_scan_large_file(path))
            continue
        payload = path.read_bytes()
        if b"\0" in payload:
            if not _is_allowed_binary_fixture(path):
                findings.append(Finding(path, 0, "unallowlisted binary file"))
            continue
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            if not _is_allowed_binary_fixture(path):
                findings.append(Finding(path, 0, "unallowlisted non-UTF-8 file"))
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
