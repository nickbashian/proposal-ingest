"""Render the host-only Compose environment from AWS SSM SecureString values."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SECRET_PARAMETERS = {
    "PROPOSAL_SECRET_KEY": "/proposal-ingest/prod/PROPOSAL_SECRET_KEY",
    "ENTRA_CLIENT_SECRET": "/proposal-ingest/prod/ENTRA_CLIENT_SECRET",
    "SHAREPOINT_CLIENT_SECRET": "/proposal-ingest/prod/SHAREPOINT_CLIENT_SECRET",
    "POSTGRES_PASSWORD": "/proposal-ingest/prod/POSTGRES_PASSWORD",
}


def _compose_value(secret_name: str, value: str) -> str:
    if not value or "\n" in value or "\r" in value:
        raise ValueError(f"SSM parameter for {secret_name} is empty or multiline")
    if secret_name == "POSTGRES_PASSWORD" and not re.fullmatch(r"[A-Fa-f0-9]{64}", value):
        raise ValueError("PostgreSQL password must be 64 hex characters for Compose URL safety")
    if secret_name == "PROPOSAL_SECRET_KEY" and len(value) < 50:
        raise ValueError("Django secret key must contain at least 50 characters")
    if "\\" in value:
        raise ValueError(f"SSM parameter for {secret_name} contains unsupported quoting")
    return "'" + value.replace("'", "\\'") + "'"


def render(template: Path, destination: Path, *, replace: bool = False) -> None:
    if destination.is_symlink() or (destination.exists() and not replace):
        raise ValueError("Refusing to overwrite an existing or symbolic-link environment file")
    content = template.read_text(encoding="utf-8")
    for name, parameter in SECRET_PARAMETERS.items():
        result = subprocess.run(
            [
                "aws",
                "ssm",
                "get-parameter",
                "--name",
                parameter,
                "--with-decryption",
                "--query",
                "Parameter.Value",
                "--output",
                "text",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        secret = result.stdout.rstrip("\r\n")
        rendered_secret = _compose_value(name, secret)
        line_prefix = name + "="
        lines = content.splitlines()
        matches = [index for index, line in enumerate(lines) if line.startswith(line_prefix)]
        if len(matches) != 1:
            raise ValueError(f"Template must contain exactly one {name} entry")
        lines[matches[0]] = line_prefix + rendered_secret
        content = "\n".join(lines) + "\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".env.production.", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, default=Path(".env.production.example"))
    parser.add_argument(
        "--destination", type=Path, default=Path("/etc/proposal-ingest/.env.production")
    )
    parser.add_argument(
        "--replace", action="store_true", help="Replace for a planned credential rotation"
    )
    args = parser.parse_args(argv)
    try:
        render(args.template, args.destination, replace=args.replace)
    except (OSError, ValueError, subprocess.CalledProcessError, FileNotFoundError):
        print(
            "Environment rendering failed; verify SSM access and template shape without displaying secret values.",
            file=sys.stderr,
        )
        return 2
    print(f"Environment file rendered with mode 0600: {args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
