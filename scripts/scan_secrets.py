"""Fail when repository files contain likely credentials or private artifacts."""

from __future__ import annotations

import ast
import hashlib
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
    "logs",
    "private_data",
    "private_evaluations",
    "private_screenshots",
    "processed_output",
    "proposal-assistant-output",
    "raw_model_responses",
    "source_documents",
}
FORBIDDEN_SUFFIXES = {".dump", ".sql.gz", ".tfstate", ".tfstate.backup"}
ALLOWED_BINARY_FIXTURE_DIGESTS = {
    "sample_data/fake_source_root/2025/2025 Fake DOE SBIR Battery Project/Budget.xlsx": (
        "f451b74b55537d93463eb7c97e25d12f269d7a3e3bc4c477dcb0cebc7709ac96"
    ),
    "sample_data/fake_source_root/2025/2025 Fake DOE SBIR Battery Project/FOA Instructions.pdf": (
        "17a85d19c3ef448bd8a7472ede3938bccb8dd2ffe0c062bc3876282f210eeeb1"
    ),
    "sample_data/fake_source_root/2025/2025 Fake DOE SBIR Battery Project/Quad Chart.pdf": (
        "bf342904441bde51526d12d4c02570ba4a11478456646064a163ea400400c937"
    ),
    "sample_data/fake_source_root/2025/2025 Fake DOE SBIR Battery Project/Quad Chart.pptx": (
        "0f277aca48a9a86964d115a4ca9f2b3d3a19db00b34afbb59e112bfcfb8f3caf"
    ),
    "sample_data/fake_source_root/2025/2025 Fake DOE SBIR Battery Project/Support Letter.docx": (
        "f36671d713e1fe6542c0eab782f264f4b7fcbd0644cb110111a2b92db2359372"
    ),
    "sample_data/fake_source_root/2025/2025 Fake DOE SBIR Battery Project/Technical Volume FINAL.docx": (
        "34cf8e87670bb0935494054e9a0fccd72b09cbd885b3b9f3a2a7b46336ad470a"
    ),
    "sample_data/fake_source_root/General/Empower Grant Activities/Grants In Progress/fake_grants_tracker.xlsx": (
        "a214f795dad46e77e994f02ec628a83ae6cf15ac84101dd333d0106ccad9aaf2"
    ),
}

SECRET_PATTERNS = {
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(
        r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|"
        r"ghs_[A-Za-z0-9]+_[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|"
        r"github_pat_[A-Za-z0-9_]{40,})\b"
    ),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
URI_CREDENTIAL_PATTERN = re.compile(
    r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@[^\s\"']+", re.IGNORECASE
)
ALLOWED_LOOPBACK_CREDENTIAL_URI = "://".join(
    ("postgresql", "proposal_ingest:local-development-only@127.0.0.1:54329/proposal_ingest_dev")
)
ASSIGNMENT_PATTERN = re.compile(
    r"\b[\"']?(?:DOCKER_AUTH_CONFIG|(?:[A-Z0-9]+_)*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY|CLIENT_?SECRET|SECRET_?ACCESS_?KEY|ACCESS_?TOKEN|AUTH_?TOKEN|BEARER_?TOKEN))[\"']?"
    r"\s*[:=]\s*(?:\"([^\"\r\n]{6,})\"|'([^'\r\n]{6,})'|([^\s#]{6,}))",
    re.IGNORECASE | re.MULTILINE,
)
SENSITIVE_NAME_PATTERN = re.compile(
    r"(?:DOCKER_AUTH_CONFIG|(?:[A-Z0-9]+_)*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY|CLIENT_?SECRET|SECRET_?ACCESS_?KEY|ACCESS_?TOKEN|AUTH_?TOKEN|BEARER_?TOKEN))",
    re.IGNORECASE,
)
SAFE_ASSIGNMENT_PATTERN = re.compile(
    r"(?:\$\{[A-Z0-9_]+\}|<[^>]+>|\*{6,}|"
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


def _python_constant_text(node: ast.expr) -> str | None:
    if not isinstance(node, ast.Constant) or isinstance(node.value, (bool, type(None))):
        return None
    if isinstance(node.value, bytes):
        return node.value.decode("utf-8", errors="replace")
    if isinstance(node.value, (str, int, float, complex)):
        return str(node.value)
    return None


def _python_target_names(node: ast.expr) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, (ast.Tuple, ast.List)):
        return [name for item in node.elts for name in _python_target_names(item)]
    return []


def _scan_python_constant_assignments(path: Path, text: str) -> list[Finding]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    findings: list[Finding] = []
    for node in ast.walk(tree):
        targets: list[ast.expr]
        value_node: ast.expr | None
        if isinstance(node, ast.Assign):
            targets = node.targets
            value_node = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value_node = node.value
        else:
            continue
        if value_node is None:
            continue
        value = _python_constant_text(value_node)
        if value is None or len(value) < 6 or _is_safe_assignment(value):
            continue
        names = [name for target in targets for name in _python_target_names(target)]
        if any(SENSITIVE_NAME_PATTERN.fullmatch(name) for name in names):
            findings.append(Finding(path, node.lineno, "non-placeholder secret assignment"))
    return findings


def scan_text(path: Path, text: str) -> list[Finding]:
    """Return likely-secret findings for decoded repository text."""

    is_python = path.suffix.casefold() == ".py"
    findings = _scan_python_constant_assignments(path, text) if is_python else []
    for number, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in SECRET_PATTERNS.items():
            if pattern.search(line):
                findings.append(Finding(path, number, kind))
        if not is_python:
            for assignment in ASSIGNMENT_PATTERN.finditer(line):
                value = assignment.group(1) or assignment.group(2) or assignment.group(3)
                if not _is_safe_assignment(value):
                    findings.append(Finding(path, number, "non-placeholder secret assignment"))
        for match in URI_CREDENTIAL_PATTERN.finditer(line):
            if match.group(0) != ALLOWED_LOOPBACK_CREDENTIAL_URI:
                findings.append(Finding(path, number, "credential in URI user-info"))
    return findings


def _with_line_offset(findings: Iterable[Finding], offset: int) -> list[Finding]:
    return [Finding(item.path, item.line + offset, item.kind) for item in findings]


def _scan_large_file(path: Path) -> list[Finding]:
    """Scan oversized UTF-8 text incrementally and fail closed on binary data."""

    if path.suffix.casefold() == ".py":
        return [Finding(path, 0, "unallowlisted oversized Python file")]
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
    relative = path.relative_to(ROOT).as_posix()
    expected_digest = ALLOWED_BINARY_FIXTURE_DIGESTS.get(relative)
    if expected_digest is None:
        return False
    with path.open("rb") as handle:
        actual_digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return actual_digest == expected_digest


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
