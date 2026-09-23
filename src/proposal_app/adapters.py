"""Provider-neutral interfaces. Only deterministic local execution is enabled here."""

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
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
        "ENTRA_TENANT_ID",
        "SHAREPOINT_SITE_ID",
        "SHAREPOINT_DRIVE_ID",
        "SHAREPOINT_CLIENT_ID",
        "SHAREPOINT_CLIENT_SECRET",
    ),
    "bedrock": ("AWS_REGION", "BEDROCK_CLASSIFICATION_MODEL_ID"),
    "s3": ("AWS_REGION", "PROPOSAL_S3_BUCKET"),
    "retrieval": ("AWS_REGION", "BEDROCK_KNOWLEDGE_BASE_ID"),
    "drafting": ("AWS_REGION", "BEDROCK_DRAFTING_MODEL_ID"),
}


def capability(name: str, configuration: dict) -> dict:
    missing = [key for key in LIVE_REQUIREMENTS.get(name, ()) if not configuration.get(key)]
    return {
        "enabled": name == "fixture" or (name == "sharepoint" and not missing),
        "missing": missing,
        "reason": (
            "local"
            if name == "fixture"
            else (
                "missing_settings"
                if missing
                else "scoped_read_only" if name == "sharepoint" else "adapter_not_implemented"
            )
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


class FixtureSliceAdapter:
    """Load the repository-owned product-slice fixture without provider calls."""

    def execute(self, payload: dict, *, idempotency_key: str) -> CallResult:
        from django.conf import settings

        if settings.MODE != "local":
            raise ProviderFailure("adapter_disabled")
        path = Path(__file__).resolve().parents[2] / settings.APP["fixture_slice_path"]
        try:
            fixture = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProviderFailure("fixture_unavailable") from exc
        required = {
            "key",
            "title",
            "display_path",
            "text",
            "locator",
            "support_kind",
            "initial_disposition",
            "reason",
        }
        if (
            not isinstance(fixture, dict)
            or not isinstance(fixture.get("revision"), str)
            or payload.get("fixture_revision") != fixture.get("revision")
            or not isinstance(fixture.get("proposal"), str)
            or not isinstance(fixture.get("family"), str)
            or not isinstance(fixture.get("items"), list)
            or any(
                not isinstance(item, dict) or not required <= item.keys()
                for item in fixture.get("items", [])
            )
        ):
            raise ProviderFailure("fixture_invalid")
        return CallResult(
            {**fixture, "synthetic": True, "operation": idempotency_key},
            Decimal("0"),
            {"provider_calls": 0},
        )


class LocalRetrievalAdapter:
    """Rank an application-filtered candidate set with deterministic lexical scoring."""

    def __init__(self, candidates: list[dict]):
        self.candidates = candidates

    def retrieve(self, query: str, generations: list[str]) -> list[dict]:
        terms = set(re.findall(r"[a-z0-9]+", query.casefold()))
        if not terms:
            return []
        allowed_generations = set(generations)
        ranked = []
        for candidate in self.candidates:
            if candidate["generation_id"] not in allowed_generations:
                continue
            searchable = f"{candidate['title']} {candidate['text']}".casefold()
            score = sum(searchable.count(term) for term in terms)
            if score:
                ranked.append({**candidate, "score": score})
        return sorted(ranked, key=lambda item: (-item["score"], item["artifact_id"]))


class DeterministicDraftingAdapter:
    """Create transparent local Markdown from a saved factual evidence packet."""

    revision = "deterministic-local-v1"
    evidence_start = "<!-- proposal-evidence:start -->"
    evidence_end = "<!-- proposal-evidence:end -->"

    @staticmethod
    def _citation(item: dict) -> str:
        locator = item["locator_label"]
        return f"- {item['text']} " f"([Source: {item['title']} — {locator}]({item['source_url']}))"

    def draft(self, packet: dict, prompt: str, *, idempotency_key: str) -> CallResult:
        evidence = packet.get("evidence", [])
        if not evidence or any(item.get("support_kind") != "factual" for item in evidence):
            raise ProviderFailure("evidence_policy_block")
        base_text = packet.get("base_text", "").strip()
        prior_evidence = packet.get("prior_evidence", [])
        if self.evidence_start in base_text:
            before, remainder = base_text.split(self.evidence_start, 1)
            if self.evidence_end in remainder:
                _, after = remainder.split(self.evidence_end, 1)
                base_text = (before + after).strip()
        elif self.evidence_end not in base_text:
            removed_prior_citation = False
            for item in prior_evidence:
                citation = self._citation(item)
                if citation in base_text:
                    base_text = base_text.replace(citation, "", 1)
                    removed_prior_citation = True
            if removed_prior_citation:
                base_text = base_text.replace("## Factual evidence", "", 1).strip()
        body = (
            f"{base_text}\n\n## Regeneration request\n\n{prompt.strip()}"
            if base_text
            else f"## Requested draft\n\n{prompt.strip()}"
        )
        citations = [self._citation(item) for item in evidence]
        evidence_block = (
            f"{self.evidence_start}\n## Factual evidence\n\n"
            + "\n".join(citations)
            + f"\n{self.evidence_end}"
        )
        text = body + "\n\n" + evidence_block + "\n"
        return CallResult(
            {"text": text, "operation": idempotency_key},
            Decimal("0"),
            {"provider_calls": 0},
        )


def adapter_for(kind: str):
    if kind == "fixture":
        return FixtureAdapter()
    if kind == "fixture-slice":
        from django.conf import settings

        if settings.MODE != "local":
            raise ProviderFailure("adapter_disabled")
        return FixtureSliceAdapter()
    raise ProviderFailure("adapter_disabled")
