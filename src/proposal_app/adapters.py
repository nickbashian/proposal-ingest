"""Provider-neutral interfaces. Only deterministic local execution is enabled here."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Protocol

from proposal_ingest.hashing import sha256_file


@dataclass(frozen=True)
class SourceIdentity:
    connector: str
    tenant: str
    site: str
    drive: str
    item: str


@dataclass(frozen=True)
class Observation:
    identity: SourceIdentity
    observation_key: str
    path: str
    upstream_version: str | None = None
    etag: str | None = None


@dataclass(frozen=True)
class Unit:
    version_id: str
    extractor_revision: str
    key: str
    locator: dict
    text: str


@dataclass(frozen=True)
class CallResult:
    value: dict
    cost: Decimal
    usage: dict


class SourceAdapter(Protocol):
    def enumerate(self, checkpoint: str | None) -> tuple[Iterable[Observation], str | None, bool]:
        """Return observations, next checkpoint, and whether the complete scope was listed."""
        ...

    def download(self, observation: Observation) -> bytes: ...


class ExtractionAdapter(Protocol):
    def extract(self, content: bytes, version_id: str, revision: str) -> list[Unit]: ...


class ClassificationAdapter(Protocol):
    def classify(self, units: list[Unit], *, idempotency_key: str) -> CallResult: ...


class ObjectStorageAdapter(Protocol):
    def put_immutable(self, digest: str, content: bytes) -> str: ...
    def get(self, key: str) -> bytes: ...


class PublicationAdapter(Protocol):
    def stage(self, artifacts: list[dict], *, idempotency_key: str) -> str: ...
    def reconcile(self, operation_id: str) -> dict: ...


class RetrievalAdapter(Protocol):
    def retrieve(self, query: str, generations: list[str]) -> list[dict]:
        """Untrusted candidates; application eligibility checks are mandatory."""
        ...


class DraftingAdapter(Protocol):
    def draft(self, packet: dict, prompt: str, *, idempotency_key: str) -> CallResult: ...


class ProviderFailure(Exception):
    def __init__(self, code: str, *, retryable=False, unknown=False, quota=False):
        super().__init__(code)
        self.code, self.retryable, self.unknown, self.quota = code, retryable, unknown, quota


def normalize_error(payload: dict, status: int) -> ProviderFailure:
    """Graph error.code and Bedrock Error.Code; never retain private error messages."""
    error = payload.get("error", payload.get("Error", {}))
    code = (
        error.get("code", error.get("Code", "provider_error"))
        if isinstance(error, dict)
        else "provider_error"
    )
    quota = code in {"ServiceQuotaExceededException", "insufficient_quota"}
    retryable = status in {408, 424, 429, 500, 502, 503, 504} or code in {
        "ThrottlingException",
        "ModelNotReadyException",
        "ModelTimeoutException",
    }
    # Server failures can follow a charged operation; retain the upper reservation.
    return ProviderFailure(
        "quota" if quota else "transient" if retryable else "denied",
        retryable=retryable,
        unknown=status in {408, 424} or status >= 500 or code == "ModelTimeoutException",
        quota=quota,
    )


LIVE_REQUIREMENTS = {
    "sharepoint": (
        "SHAREPOINT_SITE_ID",
        "SHAREPOINT_DRIVE_ID",
        "ENTRA_CLIENT_ID",
        "ENTRA_CLIENT_SECRET",
    ),
    "bedrock": ("AWS_REGION", "BEDROCK_CLASSIFICATION_MODEL_ID"),
    "s3": ("AWS_REGION", "PROPOSAL_S3_BUCKET"),
    "retrieval": ("AWS_REGION", "BEDROCK_KNOWLEDGE_BASE_ID"),
    "drafting": ("AWS_REGION", "BEDROCK_DRAFTING_MODEL_ID"),
}


def capability(name: str, configuration: dict) -> dict:
    missing = [key for key in LIVE_REQUIREMENTS.get(name, ()) if not configuration.get(key)]
    return {
        "enabled": name == "fixture",
        "missing": missing,
        "reason": (
            "local"
            if name == "fixture"
            else "missing_settings" if missing else "adapter_not_implemented"
        ),
    }


class FixtureAdapter:
    """A real job handler with synthetic data and zero provider cost."""

    def execute(self, payload: dict, *, idempotency_key: str) -> CallResult:
        from pathlib import Path

        from django.conf import settings

        # Reuse package mechanics only against a repository-owned synthetic fixture.
        fixture = Path(__file__).resolve().parents[2] / settings.APP["fixture_source_root"]
        if not fixture.is_dir():
            raise ProviderFailure("fixture_unavailable")
        files = sorted(path for path in fixture.rglob("*") if path.is_file())
        return CallResult(
            {
                "synthetic": True,
                "files": len(files),
                "hashes": [sha256_file(path) for path in files],
                "operation": idempotency_key,
            },
            Decimal("0"),
            {"provider_calls": 0},
        )


def adapter_for(kind: str):
    if kind != "fixture":
        raise ProviderFailure("adapter_disabled")
    return FixtureAdapter()
