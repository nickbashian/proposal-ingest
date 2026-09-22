import hashlib
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from scripts import dev, scan_secrets


def test_secret_scanner_accepts_placeholders_and_rejects_credentials(tmp_path: Path) -> None:
    safe = scan_secrets.scan_text(
        tmp_path / ".env.example", "CLIENT_SECRET=<set-in-secret-store>\n"
    )
    access_key = "AKIA" + "A" * 16
    unsafe = scan_secrets.scan_text(tmp_path / "settings.env", f"AWS_ACCESS_KEY_ID={access_key}\n")

    assert safe == []
    assert [finding.kind for finding in unsafe] == ["AWS access key"]


def test_secret_scanner_reports_assignment_without_echoing_value(tmp_path: Path) -> None:
    assignment = "_".join(("CLIENT", "SECRET")) + "=" + "real-value\n"
    findings = scan_secrets.scan_text(tmp_path / "settings.env", assignment)

    assert len(findings) == 1
    assert findings[0].kind == "non-placeholder secret assignment"
    assert "real-value" not in repr(findings[0])


def test_secret_scanner_requires_an_entire_placeholder_value(tmp_path: Path) -> None:
    assignment = "_".join(("CLIENT", "SECRET")) + "=" + "false-but-real\n"

    findings = scan_secrets.scan_text(tmp_path / "settings.env", assignment)

    assert [finding.kind for finding in findings] == ["non-placeholder secret assignment"]


def test_secret_scanner_detects_lowercase_symbol_prefixed_assignment(tmp_path: Path) -> None:
    key = "_".join(("client", "secret"))
    value = "!" + "real-value"

    findings = scan_secrets.scan_text(tmp_path / "settings.env", f'{key}="{value}"')

    assert [finding.kind for finding in findings] == ["non-placeholder secret assignment"]


def test_secret_scanner_detects_aws_secret_access_key_assignment(tmp_path: Path) -> None:
    key = "_".join(("aws", "secret", "access", "key"))
    value = "fictional-credential-value"

    findings = scan_secrets.scan_text(tmp_path / "settings.env", f"{key}={value}")

    assert [finding.kind for finding in findings] == ["non-placeholder secret assignment"]


def test_secret_scanner_rejects_remote_uri_credentials_but_allows_local_fixture(
    tmp_path: Path,
) -> None:
    remote = "postgresql://" + "service:super-secret@db.example.com:5432/proposals"

    remote_findings = scan_secrets.scan_text(tmp_path / "remote.env", remote)
    local_findings = scan_secrets.scan_text(
        tmp_path / ".env.example", scan_secrets.ALLOWED_LOOPBACK_CREDENTIAL_URI
    )

    assert [finding.kind for finding in remote_findings] == ["credential in URI user-info"]
    assert local_findings == []


def test_secret_scanner_rejects_private_artifact_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_file = tmp_path / "private_data" / "source.txt"
    private_file.parent.mkdir()
    private_file.write_text("fictional", encoding="utf-8")
    monkeypatch.setattr(scan_secrets, "ROOT", tmp_path)

    findings = scan_secrets.scan_paths([private_file])

    assert [(finding.line, finding.kind) for finding in findings] == [
        (0, "private/generated artifact path")
    ]


def test_secret_scanner_rejects_database_dump_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dump_file = tmp_path / "backup.sql.gz"
    dump_file.write_bytes(b"synthetic")
    monkeypatch.setattr(scan_secrets, "ROOT", tmp_path)

    findings = scan_secrets.scan_paths([dump_file])

    assert [(finding.line, finding.kind) for finding in findings] == [
        (0, "private/generated artifact path")
    ]


def test_secret_scanner_rejects_timestamped_terraform_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_file = tmp_path / "terraform.tfstate.1700000000"
    state_file.write_text("synthetic", encoding="utf-8")
    monkeypatch.setattr(scan_secrets, "ROOT", tmp_path)

    findings = scan_secrets.scan_paths([state_file])

    assert [finding.kind for finding in findings] == ["private/generated artifact path"]


def test_secret_scanner_scans_credential_beyond_large_file_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    large_file = tmp_path / "large.txt"
    access_key = "AKIA" + "B" * 16
    large_file.write_text(
        "x" * (scan_secrets.MAX_FILE_SIZE + 1) + "\n" + access_key, encoding="utf-8"
    )
    monkeypatch.setattr(scan_secrets, "ROOT", tmp_path)

    findings = scan_secrets.scan_paths([large_file])

    assert any(finding.kind == "AWS access key" for finding in findings)


def test_secret_scanner_fails_closed_for_unallowlisted_large_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    large_file = tmp_path / "large.bin"
    large_file.write_bytes(b"\0" * (scan_secrets.MAX_FILE_SIZE + 1))
    monkeypatch.setattr(scan_secrets, "ROOT", tmp_path)

    findings = scan_secrets.scan_paths([large_file])

    assert [finding.kind for finding in findings] == ["unallowlisted oversized binary file"]


def test_secret_scanner_fails_closed_for_unallowlisted_small_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary_file = tmp_path / "small.bin"
    binary_file.write_bytes(b"\0synthetic")
    monkeypatch.setattr(scan_secrets, "ROOT", tmp_path)

    findings = scan_secrets.scan_paths([binary_file])

    assert [finding.kind for finding in findings] == ["unallowlisted binary file"]


def test_binary_fixture_allowlist_requires_matching_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary_file = tmp_path / "fixtures" / "synthetic.bin"
    binary_file.parent.mkdir()
    original = b"\0synthetic"
    binary_file.write_bytes(original)
    monkeypatch.setattr(scan_secrets, "ROOT", tmp_path)
    monkeypatch.setattr(
        scan_secrets,
        "ALLOWED_BINARY_FIXTURE_DIGESTS",
        {"fixtures/synthetic.bin": hashlib.sha256(original).hexdigest()},
    )

    assert scan_secrets.scan_paths([binary_file]) == []

    binary_file.write_bytes(b"\0changed")
    findings = scan_secrets.scan_paths([binary_file])
    assert [finding.kind for finding in findings] == ["unallowlisted binary file"]


def test_docker_diagnostic_distinguishes_inactive_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dev,
        "_tool_version",
        lambda name, arguments=("--version",): dev.CheckResult(name, "PASS", "Docker 28"),
    )

    def fake_run(command: list[str], **_: object) -> CompletedProcess[str]:
        if command[1:3] == ["compose", "version"]:
            return CompletedProcess(command, 0, "Docker Compose v2", "")
        return CompletedProcess(command, 1, "", "engine unavailable")

    monkeypatch.setattr(dev, "_run", fake_run)

    results = dev._docker_results()

    assert [result.status for result in results] == ["PASS", "PASS", "WARN"]
    assert "inactive or unreachable" in results[-1].detail


def test_python_diagnostic_rejects_314(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dev.sys, "version_info", (3, 14, 0))
    monkeypatch.setattr(dev.platform, "python_version", lambda: "3.14.0")

    result = dev._python_result()

    assert result.status == "FAIL"
    assert "require Python 3.13 exactly" in result.detail


def test_linux_browser_install_includes_system_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_subprocess_run(command: list[str], **_: object) -> CompletedProcess[str]:
        calls.append(command)
        return CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(dev.sys, "platform", "linux")
    monkeypatch.setattr(dev.subprocess, "run", fake_subprocess_run)

    dev.install_browser()

    assert calls == [[dev.sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"]]


def test_mock_run_is_forced_to_synthetic_source_and_mock_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_subprocess_run(command: list[str], **_: object) -> CompletedProcess[str]:
        calls.append(command)
        return CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(dev.subprocess, "run", fake_subprocess_run)

    dev.mock_run(tmp_path / "output")

    command = calls[0]
    assert command[2:4] == ["proposal_ingest.cli", "run-all"]
    assert command[command.index("--source-root") + 1] == str(
        dev.ROOT / "sample_data" / "fake_source_root"
    )
    assert command[command.index("--output-root") + 1] == str((tmp_path / "output").resolve())
    assert command[-1] == "--mock-bedrock"


def test_dev_check_includes_config_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_subprocess_run(command: list[str], **_: object) -> CompletedProcess[str]:
        calls.append(command)
        return CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(dev.subprocess, "run", fake_subprocess_run)

    dev.run_checks()

    config_command = next(command for command in calls if command[-1] == "config-check")
    pytest_command = next(command for command in calls if "pytest" in command)
    assert calls.index(config_command) < calls.index(pytest_command)


def test_bootstrap_refuses_onedrive_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dev, "ROOT", Path("C:/Users/example/OneDrive/project"))

    with pytest.raises(RuntimeError, match="under OneDrive"):
        dev._assert_safe_checkout()


def test_config_validation_rejects_local_auth_in_production() -> None:
    values = dev.read_env_file(dev.ROOT / ".env.example")
    values["PROPOSAL_APP_ENV"] = "production"

    errors = dev.validate_env(values)

    assert "PROPOSAL_LOCAL_AUTH_ENABLED must be false in production" in errors
    assert "ENTRA_TENANT_ID is required in production" in errors


def test_config_validation_rejects_blank_required_value() -> None:
    values = dev.read_env_file(dev.ROOT / ".env.example")
    values["DATABASE_URL"] = "   "
    values["PROPOSAL_STORAGE_BACKEND"] = "unsupported"

    errors = dev.validate_env(values)

    assert "missing or blank setting: DATABASE_URL" in errors
    assert "PROPOSAL_STORAGE_BACKEND must be local or s3" in errors


@pytest.mark.parametrize(
    ("backend", "setting", "expected"),
    [
        ("local", "PROPOSAL_LOCAL_STORAGE_ROOT", "local storage"),
        ("s3", "PROPOSAL_S3_BUCKET", "s3 storage"),
    ],
)
def test_config_validation_requires_backend_setting(
    backend: str, setting: str, expected: str
) -> None:
    values = dev.read_env_file(dev.ROOT / ".env.example")
    values["PROPOSAL_STORAGE_BACKEND"] = backend
    values[setting] = ""

    errors = dev.validate_env(values)

    assert any(expected in error for error in errors)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_config_validation_rejects_non_finite_cost_limits(value: str) -> None:
    values = dev.read_env_file(dev.ROOT / ".env.example")
    values["SINGLE_JOB_COST_LIMIT_USD"] = value

    errors = dev.validate_env(values)

    assert "SINGLE_JOB_COST_LIMIT_USD must be a finite value greater than zero" in errors
