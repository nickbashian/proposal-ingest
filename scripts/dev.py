"""Cross-platform development setup, diagnostics, and smoke-test commands."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
LOCK_FILE = ROOT / "requirements-dev.lock"
COMPOSE_FILE = ROOT / "compose.dev.yml"
REQUIRED_PYTHON = (3, 13)
ENV_REQUIRED_KEYS = {
    "PROPOSAL_APP_ENV",
    "PROPOSAL_LOCAL_AUTH_ENABLED",
    "DATABASE_URL",
    "PROPOSAL_STORAGE_BACKEND",
    "AWS_REGION",
    "MOCK_BEDROCK",
    "JOB_WORKER_CONCURRENCY",
    "JOB_MAX_RETRIES",
    "MONTHLY_VARIABLE_COST_LIMIT_USD",
    "SINGLE_JOB_COST_LIMIT_USD",
}
SUPPORTED_STORAGE_BACKENDS = {"local", "s3"}


def _configure_browser_cache() -> Path:
    """Keep browser tooling in the owner's nonsynced Codex root by default."""

    default = Path.home() / ".codex" / "proposal-ingest" / "playwright"
    configured = Path(os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(default)))
    return configured


@dataclass(frozen=True)
class CheckResult:
    """One environment diagnostic result."""

    name: str
    status: str
    detail: str
    next_action: str = ""


def _run(
    command: Sequence[str],
    *,
    check: bool = False,
    cwd: Path = ROOT,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    return " ".join(output.split())


def _tool_version(name: str, arguments: Sequence[str] = ("--version",)) -> CheckResult:
    executable = shutil.which(name)
    if not executable:
        return CheckResult(
            name, "WARN", "missing executable", f"Install {name} and rerun diagnose."
        )
    try:
        result = _run([executable, *arguments])
    except (OSError, subprocess.SubprocessError) as exc:
        return CheckResult(name, "WARN", f"installed but unusable: {exc}")
    detail = _combined_output(result) or executable
    status = "PASS" if result.returncode == 0 else "WARN"
    return CheckResult(name, status, detail[:300])


def _python_result() -> CheckResult:
    version = platform.python_version()
    if sys.version_info[:2] != REQUIRED_PYTHON:
        return CheckResult(
            "Python",
            "FAIL",
            f"running {version}; this lock and project require Python 3.13 exactly",
            "Run this command with py -3.13 on Windows or python3.13 on Linux.",
        )
    return CheckResult("Python", "PASS", f"{version} ({sys.executable})")


def _git_result() -> CheckResult:
    version = _tool_version("git")
    if version.status != "PASS":
        return version
    result = _run(["git", "rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        return CheckResult("Git", "FAIL", "Git is installed, but this is not a worktree")
    return CheckResult("Git", "PASS", version.detail)


def _docker_results() -> list[CheckResult]:
    version = _tool_version("docker")
    if version.status != "PASS":
        return [
            version,
            CheckResult("Docker Compose", "WARN", "not checked because Docker is missing"),
        ]

    compose = _run(["docker", "compose", "version"])
    compose_result = CheckResult(
        "Docker Compose",
        "PASS" if compose.returncode == 0 else "WARN",
        (_combined_output(compose) or "Compose plugin unavailable")[:300],
        "Install the Docker Compose plugin." if compose.returncode else "",
    )
    engine = _run(["docker", "info", "--format", "{{.ServerVersion}}"])
    if engine.returncode:
        engine_result = CheckResult(
            "Docker engine",
            "WARN",
            "Docker CLI is installed, but the engine is inactive or unreachable",
            "Start Docker Desktop (Windows) or the Docker service (Linux), then rerun diagnose.",
        )
    else:
        engine_result = CheckResult("Docker engine", "PASS", _combined_output(engine))
    return [version, compose_result, engine_result]


def _github_result() -> CheckResult:
    version = _tool_version("gh")
    if version.status != "PASS":
        return version
    auth = _run(["gh", "auth", "status"])
    if auth.returncode:
        return CheckResult(
            "GitHub CLI",
            "WARN",
            "installed; authentication is missing or invalid",
            "Run: gh auth login -h github.com",
        )
    return CheckResult("GitHub CLI", "PASS", "installed and authenticated")


def _aws_results(check_auth: bool) -> list[CheckResult]:
    version = _tool_version("aws")
    if version.status != "PASS":
        return [version]
    profiles = _run(["aws", "configure", "list-profiles"])
    available = [line.strip() for line in profiles.stdout.splitlines() if line.strip()]
    selected = os.environ.get("AWS_PROFILE") or (available[0] if len(available) == 1 else "")
    if not selected:
        return [
            version,
            CheckResult(
                "AWS sign-in",
                "WARN",
                "CLI installed; no unambiguous named profile is selected",
                "Set AWS_PROFILE to the intended named/SSO profile. Do not use long-lived keys.",
            ),
        ]
    if not check_auth:
        return [
            version,
            CheckResult(
                "AWS sign-in",
                "WARN",
                f"profile '{selected}' is configured; live identity was not checked",
                "Run diagnose --check-auth in a private session when connecting AWS.",
            ),
        ]
    identity = _run(["aws", "sts", "get-caller-identity", "--profile", selected], timeout=45)
    if identity.returncode:
        return [
            version,
            CheckResult(
                "AWS sign-in",
                "WARN",
                f"profile '{selected}' did not authenticate",
                f"Run: aws sso login --profile {selected}",
            ),
        ]
    return [version, CheckResult("AWS sign-in", "PASS", f"authenticated profile '{selected}'")]


def _coderabbit_result() -> CheckResult:
    command = shutil.which("coderabbit") or shutil.which("cr")
    if not command:
        return CheckResult(
            "CodeRabbit",
            "WARN",
            "missing executable and authentication",
            (
                "Inspect the official Windows installer, install the CLI, then run "
                "cr auth login and cr doctor; alternatively enable the GitHub app for this repository."
            ),
        )
    version = _run([command, "--version"])
    auth = _run([command, "auth", "status"])
    if auth.returncode:
        return CheckResult(
            "CodeRabbit",
            "WARN",
            f"installed ({_combined_output(version)}); sign-in is missing or invalid",
            "Run: cr auth login, followed by cr doctor.",
        )
    return CheckResult(
        "CodeRabbit", "PASS", f"installed and authenticated: {_combined_output(version)}"
    )


def _playwright_result(run_browser: bool) -> CheckResult:
    if importlib.util.find_spec("playwright") is None:
        return CheckResult(
            "Playwright",
            "WARN",
            "Python package is not installed",
            "Run bootstrap --with-browser.",
        )
    if not run_browser:
        return CheckResult(
            "Playwright",
            "WARN",
            "Python package installed; browser launch was not checked",
            "Run diagnose --check-browser or browser-smoke.",
        )
    try:
        browser_smoke()
    except Exception as exc:  # Playwright exposes several runtime exception types.
        return CheckResult(
            "Playwright",
            "WARN",
            f"package installed, but Chromium did not launch: {exc}",
            "Run: python -m playwright install chromium",
        )
    return CheckResult("Playwright", "PASS", "Chromium launched and rendered a local page")


def diagnose(*, check_auth: bool = False, check_browser: bool = False) -> list[CheckResult]:
    """Return development environment diagnostics without installing anything."""

    results = [_git_result(), _python_result(), _tool_version("make")]
    results.extend(_docker_results())
    results.extend(_aws_results(check_auth))
    results.extend(
        [
            _github_result(),
            _tool_version("node"),
            _playwright_result(check_browser),
            _coderabbit_result(),
        ]
    )
    return results


def _venv_python() -> Path:
    relative = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    return VENV / relative


def _python_launcher() -> list[str]:
    if sys.version_info[:2] == REQUIRED_PYTHON:
        return [sys.executable]
    candidates = (["py", "-3.13"], ["python3.13"])
    for candidate in candidates:
        if not shutil.which(candidate[0]):
            continue
        probe = _run(
            [*candidate, "-c", "import sys; raise SystemExit(sys.version_info[:2] != (3, 13))"]
        )
        if probe.returncode == 0:
            return list(candidate)
    raise RuntimeError("Python 3.13 is required; no exact 3.13 interpreter was found.")


def _assert_safe_checkout() -> None:
    if "onedrive" in str(ROOT).casefold():
        raise RuntimeError(
            "This checkout is under OneDrive. Move it to a nonsynced path before installing dependencies."
        )


def read_env_file(path: Path) -> dict[str, str]:
    """Read simple KEY=VALUE settings without logging any values."""

    values: dict[str, str] = {}
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path.name}:{number} is not a KEY=VALUE setting")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in values:
            raise ValueError(f"{path.name}:{number} has an empty or duplicate key")
        values[key] = value.strip()
    return values


def validate_env(values: dict[str, str], *, production: bool = False) -> list[str]:
    """Return actionable setting-name errors while never exposing secret values."""

    errors = [
        f"missing or blank setting: {key}"
        for key in sorted(key for key in ENV_REQUIRED_KEYS if not values.get(key, "").strip())
    ]
    if values.get("PROPOSAL_APP_ENV") not in {"local", "production"}:
        errors.append("PROPOSAL_APP_ENV must be local or production")
    if values.get("PROPOSAL_STORAGE_BACKEND") not in SUPPORTED_STORAGE_BACKENDS:
        errors.append("PROPOSAL_STORAGE_BACKEND must be local or s3")
    boolean_keys = {"PROPOSAL_LOCAL_AUTH_ENABLED", "MOCK_BEDROCK", "SAVE_RAW_MODEL_RESPONSES"}
    for key in sorted(boolean_keys & values.keys()):
        if values[key].casefold() not in {"true", "false"}:
            errors.append(f"{key} must be true or false")
    if production or values.get("PROPOSAL_APP_ENV") == "production":
        if values.get("PROPOSAL_LOCAL_AUTH_ENABLED", "").casefold() != "false":
            errors.append("PROPOSAL_LOCAL_AUTH_ENABLED must be false in production")
        for key in ("ENTRA_TENANT_ID", "ENTRA_CLIENT_ID", "ENTRA_REDIRECT_URI"):
            if not values.get(key):
                errors.append(f"{key} is required in production")
    for key in ("JOB_WORKER_CONCURRENCY", "JOB_LEASE_SECONDS", "JOB_MAX_RETRIES"):
        if key not in values:
            continue
        try:
            number = int(values[key])
        except ValueError:
            number = -1
        if number < 1:
            errors.append(f"{key} must be a positive integer")
    for key in ("MONTHLY_VARIABLE_COST_LIMIT_USD", "SINGLE_JOB_COST_LIMIT_USD"):
        if key not in values:
            continue
        try:
            amount = float(values[key])
        except ValueError:
            amount = -1
        if amount <= 0:
            errors.append(f"{key} must be greater than zero")
    return errors


def config_check(path: Path, *, production: bool) -> None:
    values = read_env_file(path)
    errors = validate_env(values, production=production)
    if errors:
        raise RuntimeError("; ".join(errors))
    print(f"Configuration shape passed ({len(values)} settings; values not displayed).")


def bootstrap(*, with_browser: bool) -> None:
    """Create the local environment and install locked dependencies."""

    _assert_safe_checkout()
    _configure_browser_cache()
    launcher = _python_launcher()
    if not _venv_python().exists():
        subprocess.run([*launcher, "-m", "venv", str(VENV)], cwd=ROOT, check=True)
    python = str(_venv_python())
    subprocess.run([python, "-m", "pip", "install", "--requirement", str(LOCK_FILE)], check=True)
    subprocess.run(
        [
            python,
            "-m",
            "pip",
            "install",
            "--no-build-isolation",
            "--no-deps",
            "--editable",
            str(ROOT),
        ],
        check=True,
    )
    if with_browser:
        subprocess.run([python, "scripts/dev.py", "install-browser"], cwd=ROOT, check=True)


def install_browser() -> None:
    """Install Chromium in the shared cache plus supported Linux libraries."""

    _configure_browser_cache()
    command = [sys.executable, "-m", "playwright", "install"]
    if sys.platform.startswith("linux"):
        command.append("--with-deps")
    command.append("chromium")
    subprocess.run(command, cwd=ROOT, check=True)


def browser_smoke() -> None:
    """Launch Chromium and render local content without network access."""

    _configure_browser_cache()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_content("<title>proposal-ingest browser smoke</title><h1>ready</h1>")
        if page.title() != "proposal-ingest browser smoke" or page.text_content("h1") != "ready":
            raise RuntimeError("Chromium launched but did not render the expected local page.")
        browser.close()


def run_checks() -> None:
    """Run the same no-network, no-provider checks used by CI."""

    python = str(_venv_python() if _venv_python().exists() else Path(sys.executable))
    commands = [
        [python, "-m", "black", "--check", "src", "tests", "scripts"],
        [python, "-m", "ruff", "check", "src", "tests", "scripts"],
        [python, "-m", "codespell_lib"],
        [python, "-m", "mypy", "src", "scripts"],
        [python, "scripts/scan_secrets.py"],
        [python, "-m", "pytest", "--basetemp", "tmp/pytest-basetemp-dev"],
        [python, "scripts/dev.py", "browser-smoke"],
    ]
    for command in commands:
        subprocess.run(command, cwd=ROOT, check=True)


def mock_run(output_root: Path) -> None:
    """Run the existing end-to-end pipeline with deterministic local inference."""

    python = str(_venv_python() if _venv_python().exists() else Path(sys.executable))
    subprocess.run(
        [
            python,
            "-m",
            "proposal_ingest.cli",
            "run-all",
            "--source-root",
            str(ROOT / "sample_data" / "fake_source_root"),
            "--output-root",
            str(output_root.resolve()),
            "--mock-bedrock",
        ],
        cwd=ROOT,
        check=True,
    )


def _compose(arguments: Sequence[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return _run(["docker", "compose", "-f", str(COMPOSE_FILE), *arguments], timeout=timeout)


def db_up() -> None:
    result = _compose(["up", "--detach", "--wait", "postgres"], timeout=60)
    if result.returncode:
        raise RuntimeError(_combined_output(result))


def db_smoke() -> None:
    """Check PostgreSQL health, restart persistence, and logical backup output."""

    db_up()
    psql = [
        "exec",
        "-T",
        "postgres",
        "psql",
        "--username",
        "proposal_ingest",
        "--dbname",
        "proposal_ingest_dev",
        "--set",
        "ON_ERROR_STOP=1",
        "--command",
    ]
    setup_sql = (
        "CREATE TABLE IF NOT EXISTS mvp00_smoke (id integer PRIMARY KEY, value text NOT NULL); "
        "INSERT INTO mvp00_smoke VALUES (1, 'persistent') "
        "ON CONFLICT (id) DO UPDATE SET value = EXCLUDED.value;"
    )
    setup = _compose([*psql, setup_sql])
    if setup.returncode:
        raise RuntimeError(_combined_output(setup))
    restart = _compose(["restart", "postgres"], timeout=60)
    if restart.returncode:
        raise RuntimeError(_combined_output(restart))
    for _ in range(20):
        query = _compose([*psql, "SELECT value FROM mvp00_smoke WHERE id = 1;"])
        if query.returncode == 0 and "persistent" in query.stdout:
            break
        time.sleep(1)
    else:
        raise RuntimeError("PostgreSQL did not preserve the smoke row across restart.")
    dump = _compose(
        [
            "exec",
            "-T",
            "postgres",
            "pg_dump",
            "--username",
            "proposal_ingest",
            "--dbname",
            "proposal_ingest_dev",
            "--schema-only",
        ]
    )
    if dump.returncode or "CREATE TABLE public.mvp00_smoke" not in dump.stdout:
        raise RuntimeError("PostgreSQL logical backup smoke test failed.")


def db_down(*, volumes: bool) -> None:
    arguments = ["down", "--remove-orphans"]
    if volumes:
        arguments.append("--volumes")
    result = _compose(arguments)
    if result.returncode:
        raise RuntimeError(_combined_output(result))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    diagnose_parser = subparsers.add_parser("diagnose", help="Inspect tools and connection state")
    diagnose_parser.add_argument(
        "--check-auth", action="store_true", help="Run read-only live auth probes"
    )
    diagnose_parser.add_argument(
        "--check-browser", action="store_true", help="Launch local Chromium"
    )
    diagnose_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    diagnose_parser.add_argument("--strict", action="store_true", help="Treat warnings as failures")

    bootstrap_parser = subparsers.add_parser(
        "bootstrap", help="Install the locked local environment"
    )
    bootstrap_parser.add_argument("--with-browser", action="store_true", help="Install Chromium")

    subparsers.add_parser("check", help="Run the complete local/CI check path")
    subparsers.add_parser("install-browser", help="Install Chromium in the shared tooling cache")
    subparsers.add_parser("browser-smoke", help="Launch Chromium against a local page")

    config_parser = subparsers.add_parser(
        "config-check", help="Validate settings without echoing values"
    )
    config_parser.add_argument("--path", type=Path, default=ROOT / ".env.example")
    config_parser.add_argument("--production", action="store_true")

    mock_parser = subparsers.add_parser("mock-run", help="Run the existing pipeline without AWS")
    mock_parser.add_argument("--output-root", type=Path, default=ROOT / "tmp" / "mvp00-mock")

    subparsers.add_parser("db-up", help="Start the disposable development PostgreSQL service")
    subparsers.add_parser("db-smoke", help="Test PostgreSQL persistence and logical backup")
    subparsers.add_parser("db-down", help="Stop development services and preserve data")
    subparsers.add_parser(
        "db-reset", help="Stop services and delete only the disposable dev volume"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "diagnose":
            results = diagnose(check_auth=args.check_auth, check_browser=args.check_browser)
            if args.json:
                print(json.dumps([asdict(result) for result in results], indent=2))
            else:
                for result in results:
                    print(f"[{result.status:<4}] {result.name}: {result.detail}")
                    if result.next_action:
                        print(f"       Next: {result.next_action}")
            failing = {"FAIL", "WARN"} if args.strict else {"FAIL"}
            return 1 if any(result.status in failing for result in results) else 0
        if args.command == "bootstrap":
            bootstrap(with_browser=args.with_browser)
        elif args.command == "install-browser":
            install_browser()
        elif args.command == "check":
            run_checks()
        elif args.command == "browser-smoke":
            browser_smoke()
        elif args.command == "config-check":
            config_check(args.path, production=args.production)
        elif args.command == "mock-run":
            mock_run(args.output_root)
        elif args.command == "db-up":
            db_up()
        elif args.command == "db-smoke":
            db_smoke()
        elif args.command == "db-down":
            db_down(volumes=False)
        elif args.command == "db-reset":
            db_down(volumes=True)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
