"""Read-only local preflight for the MVP-08 service connection session.

This command checks presence and unresolved template placeholders. It never
prints values or contacts a provider; live probes remain explicit operator steps.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    action: str


def _parse_env_file(path: Path) -> dict[str, str]:
    """Read simple KEY=VALUE lines without expanding or displaying values."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if not match:
            continue
        key, value = match.groups()
        if value.startswith(('"', "'")):
            closing_quote = value.find(value[0], 1)
            if closing_quote >= 0:
                value = value[1:closing_quote]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


def inspect_connections(values: Mapping[str, str]) -> list[Check]:
    """Return configuration checks without including supplied values."""

    def configured(value: str) -> bool:
        candidate = value.strip().lower()
        return bool(candidate) and not any(
            marker in candidate
            for marker in ("replace_with", "${", "example.org", "example.com", "example.net")
        )

    def check(name: str, keys: Sequence[str], action: str) -> Check:
        missing = [key for key in keys if not configured(values.get(key, ""))]
        if missing:
            return Check(
                name, "NEEDS CONFIG", "Unset or placeholder: " + ", ".join(missing), action
            )
        return Check(
            name,
            "CONFIGURED",
            f"All {len(keys)} required settings are present; values redacted.",
            action,
        )

    results = [
        check(
            "Application database",
            ("DATABASE_URL",),
            "Set DATABASE_URL to the intended application database.",
        ),
        check(
            "AWS identity and region",
            ("AWS_PROFILE", "AWS_REGION"),
            "Set an SSO or named AWS_PROFILE and the approved AWS_REGION; then run the opt-in identity probe.",
        ),
        check(
            "Bedrock and publication",
            (
                "BEDROCK_CLASSIFICATION_MODEL_ID",
                "BEDROCK_CLASSIFICATION_ESTIMATE_USD_PER_CALL",
                "BEDROCK_DRAFTING_MODEL_ID",
                "PROPOSAL_DRAFTING_RESERVATION_USD",
                "BEDROCK_KNOWLEDGE_BASE_ID",
                "BEDROCK_DATA_SOURCE_ID",
                "PROPOSAL_CURATED_BUCKET",
            ),
            "Set approved model/profile IDs, positive per-call estimates, knowledge base/data source IDs, and curated bucket after account review.",
        ),
        check(
            "Web sign-in (Entra OIDC)",
            (
                "OIDC_ISSUER",
                "ENTRA_TENANT_ID",
                "ENTRA_CLIENT_ID",
                "ENTRA_CLIENT_SECRET",
                "ENTRA_REDIRECT_URI",
            ),
            "Register the app and set the issuer, tenant, client, secret, and exact redirect URI in private configuration.",
        ),
        check(
            "Read-only SharePoint connector",
            (
                "ENTRA_TENANT_ID",
                "SHAREPOINT_SITE_ID",
                "SHAREPOINT_DRIVE_ID",
                "SHAREPOINT_CLIENT_ID",
                "SHAREPOINT_CLIENT_SECRET",
            ),
            "Grant selected-site read access and set the site, drive, and connector credentials privately; select the seed proposal folder when running sync_sources.",
        ),
    ]
    if values.get("PROPOSAL_STORAGE_BACKEND", "local").strip().lower() == "s3":
        results.append(
            Check(
                "S3 storage",
                "NEEDS IMPLEMENTATION",
                "Application snapshots currently use durable local object storage.",
                "Use encrypted local storage plus off-host backups, or implement and test S3 snapshot storage before selecting it.",
            )
        )
    return results


def _load_values(env_file: Path) -> dict[str, str]:
    values = _parse_env_file(env_file)
    values.update(os.environ)
    return values


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ROOT / ".env",
        help="private env file to inspect (default: repository .env)",
    )
    args = parser.parse_args(argv)
    checks = inspect_connections(_load_values(args.env_file))
    print(
        "MVP-08 connection preflight (offline; no provider calls; setting values are never shown)"
    )
    for item in checks:
        print(f"[{item.status}] {item.name}: {item.detail}")
        if item.status != "CONFIGURED":
            print(f"  Action: {item.action}")
    print("\nOptional live probes (run only during the approved connection session):")
    print(
        "  AWS identity: aws sts get-caller-identity --profile $env:AWS_PROFILE > $null; if ($LASTEXITCODE -ne 0) { throw 'AWS identity probe failed' }"
    )
    print(
        "  Bedrock access: aws bedrock list-foundation-models --region $env:AWS_REGION > $null; if ($LASTEXITCODE -ne 0) { throw 'Bedrock API probe failed' }"
    )
    print(
        "  Managed KB access: aws bedrock-agent list-knowledge-bases --region $env:AWS_REGION > $null; if ($LASTEXITCODE -ne 0) { throw 'Managed KB API probe failed' }"
    )
    print(
        "  Entra/Graph and SharePoint probes require the approved app identity and selected-site read grant; use the application's scoped connector diagnostics."
    )
    return 0 if all(item.status == "CONFIGURED" for item in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
