"""Private-manifest validation and aggregate MVP-09 acceptance scoring.

This module is intentionally stdlib-only: it cannot contact providers or load
application credentials. Reports contain metric counts only, never case IDs.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

SCHEMA_VERSION = 1
SPLITS = {"calibration", "seed_frozen", "expansion_held_out"}
METRICS = {"A01", "A02", "A04", "A05", "A06", "A07", "A08", "A19"}
DISPOSITIONS = {"processed", "excluded", "deferred", "failed", "awaiting_decision"}
PRIVATE_TEXT_KEYS = {"excerpt", "text", "prompt", "source_text", "raw_response"}
MANIFEST_KEYS = {
    "schema_version",
    "suite_id",
    "kind",
    "source_snapshot",
    "policy_revision",
    "schema_revision",
    "prompt_revision",
    "sampling_method",
    "frozen_by",
    "frozen_at",
    "groups",
    "inventory_counts",
    "cases",
    "revision",
}
CASE_DATA_KEYS = {
    "A01": {"disposition", "reason", "recovery_route"},
    "A02": {"valuable", "retained", "essential_conditions_preserved", "critical"},
    "A04": {"answerable", "required_support_ids", "top10_eligible_ids"},
    "A05": {"case_kind", "observed", "unsupported_claims"},
    "A06": {"citation_resolves", "semantic_support"},
    "A07": {"critical_error", "flagged"},
    "A08": {"usefulness_rating", "ordinary_editing_only"},
    "A19": {
        "discovered_items",
        "extracted_passages",
        "supported_nonsensitive",
        "automatically_tagged",
        "automatically_resolved",
        "substantive_questions",
        "human_decisions",
        "review_seconds",
        "unsupported_or_failed",
    },
}
REQUIRED_CASE_DATA_KEYS = {
    **CASE_DATA_KEYS,
    "A01": {"disposition", "reason"},
}


class ManifestError(ValueError):
    """A malformed, unfrozen, or split-leaking evaluation manifest."""


def _canonical_bytes(document: dict[str, Any]) -> bytes:
    revisionless = {key: value for key, value in document.items() if key != "revision"}
    return json.dumps(
        revisionless, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def freeze_manifest(document: dict[str, Any]) -> dict[str, Any]:
    """Validate a candidate, bind its exact content to a SHA-256 revision, and return it."""
    candidate = dict(document)
    candidate.pop("revision", None)
    if candidate.get("kind") != "synthetic":
        candidate.setdefault("frozen_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    _validate_manifest(candidate, require_revision=False)
    candidate["revision"] = "sha256:" + hashlib.sha256(_canonical_bytes(candidate)).hexdigest()
    validate_manifest(candidate)
    return candidate


def validate_manifest(document: dict[str, Any]) -> None:
    """Validate structure, frozen digest, case grouping, and private-text exclusions."""
    _validate_manifest(document, require_revision=True)
    expected = "sha256:" + hashlib.sha256(_canonical_bytes(document)).hexdigest()
    if document["revision"] != expected:
        raise ManifestError("Manifest revision does not match its frozen contents")


def _validate_manifest(document: dict[str, Any], *, require_revision: bool) -> None:
    if (
        not isinstance(document, dict)
        or type(document.get("schema_version")) is not int
        or document.get("schema_version") != SCHEMA_VERSION
    ):
        raise ManifestError("Unsupported manifest schema version")
    if set(document) - MANIFEST_KEYS:
        raise ManifestError("Manifest contains unsupported fields")
    if not isinstance(document.get("suite_id"), str) or not document["suite_id"].strip():
        raise ManifestError("suite_id is required")
    if not isinstance(document.get("kind"), str) or document.get("kind") not in {
        "calibration",
        "seed_frozen",
        "expansion_held_out",
        "synthetic",
    }:
        raise ManifestError(
            "kind must identify calibration, frozen seed, held-out expansion, or synthetic data"
        )
    if (
        not isinstance(document.get("source_snapshot"), str)
        or not document["source_snapshot"].strip()
    ):
        raise ManifestError("source_snapshot is required")
    for field in ("policy_revision", "schema_revision", "prompt_revision", "sampling_method"):
        if not isinstance(document.get(field), str) or not document[field].strip():
            raise ManifestError(f"{field} is required")
    if document.get("kind") != "synthetic" and (
        not document.get("frozen_by") or not document.get("frozen_at")
    ):
        raise ManifestError("Private suites require frozen_by and frozen_at")
    if require_revision and not isinstance(document.get("revision"), str):
        raise ManifestError("Manifest must be frozen before scoring")
    inventory_counts = document.get("inventory_counts")
    if not isinstance(inventory_counts, dict) or not inventory_counts:
        raise ManifestError(
            "inventory_counts must record the independent discovered-item denominator by family"
        )
    for family, count in inventory_counts.items():
        if not isinstance(family, str) or not re.fullmatch(r"F[0-9]{1,2}", family):
            raise ManifestError("inventory_counts keys must be opaque family codes")
        if type(count) is not int or count < 0:
            raise ManifestError("inventory_counts values must be nonnegative integers")

    groups = document.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ManifestError("groups must be a nonempty list")
    group_splits: dict[str, str] = {}
    fingerprint_groups: dict[str, tuple[str, str]] = {}
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            raise ManifestError(f"groups[{index}] must be an object")
        if set(group) - {"group_key", "split", "source_fingerprints"}:
            raise ManifestError(f"groups[{index}] contains unsupported fields")
        key, split = group.get("group_key"), group.get("split")
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(split, str)
            or split not in SPLITS | {"synthetic"}
        ):
            raise ManifestError(f"groups[{index}] needs a key and supported split")
        if split != document["kind"]:
            raise ManifestError("Each manifest must contain one evaluation split matching its kind")
        if key in group_splits:
            raise ManifestError("Each leakage group must be declared exactly once")
        group_splits[key] = split
        fingerprints = group.get("source_fingerprints", [])
        if not isinstance(fingerprints, list):
            raise ManifestError(f"groups[{index}].source_fingerprints must be a list")
        for fingerprint in fingerprints:
            if not isinstance(fingerprint, str) or not re.fullmatch(
                r"hmac-sha256:[0-9a-f]{64}", fingerprint
            ):
                raise ManifestError("Source fingerprints must be private HMAC-SHA256 values")
            group_and_split = (key, split)
            if (
                fingerprint in fingerprint_groups
                and fingerprint_groups[fingerprint] != group_and_split
            ):
                raise ManifestError(
                    "Related source fingerprints must remain in one leakage group and split"
                )
            fingerprint_groups[fingerprint] = group_and_split

    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ManifestError("cases must be a nonempty list")
    case_keys: set[str] = set()
    a19_families: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ManifestError(f"cases[{index}] must be an object")
        if set(case) != {"case_key", "group_key", "split", "family_key", "metric", "data"}:
            raise ManifestError(f"cases[{index}] contains unsupported fields")
        key, group_key, split, family, metric, data = (
            case.get("case_key"),
            case.get("group_key"),
            case.get("split"),
            case.get("family_key"),
            case.get("metric"),
            case.get("data"),
        )
        if not isinstance(key, str) or not key or key in case_keys:
            raise ManifestError(f"cases[{index}] needs a unique case_key")
        case_keys.add(key)
        if (
            not isinstance(group_key, str)
            or not isinstance(split, str)
            or group_key not in group_splits
            or split != group_splits.get(group_key)
        ):
            raise ManifestError(f"cases[{index}] split does not match its declared leakage group")
        if not isinstance(family, str) or not re.fullmatch(r"F[0-9]{1,2}", family):
            raise ManifestError(f"cases[{index}] family_key must be an opaque code such as F1")
        if not isinstance(metric, str) or metric not in METRICS or not isinstance(data, dict):
            raise ManifestError(f"cases[{index}] has an unsupported metric or data object")
        if _contains_private_text_key(case):
            raise ManifestError(f"cases[{index}] must reference source units, not copy source text")
        if family not in inventory_counts:
            raise ManifestError(
                f"cases[{index}] family is absent from independent inventory_counts"
            )
        if not REQUIRED_CASE_DATA_KEYS[metric] <= set(data) or set(data) - CASE_DATA_KEYS[metric]:
            raise ManifestError(f"cases[{index}] data does not match the metric schema")
        _validate_case_data(metric, data, index)
        if metric == "A19":
            if family in a19_families:
                raise ManifestError("A19 requires at most one aggregate row per family")
            if data["discovered_items"] != inventory_counts[family]:
                raise ManifestError(
                    f"cases[{index}] A19 discovered_items must match the independent inventory"
                )
            a19_families.add(family)


def _contains_private_text_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            (isinstance(key, str) and key.casefold() in PRIVATE_TEXT_KEYS)
            or _contains_private_text_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_private_text_key(item) for item in value)
    return False


def _need_bool(data: dict[str, Any], fields: Iterable[str], index: int) -> None:
    if any(type(data.get(field)) is not bool for field in fields):
        raise ManifestError(f"cases[{index}] requires boolean evidence fields")


def _need_count(data: dict[str, Any], field: str, index: int) -> int:
    value = data.get(field)
    if type(value) is not int or value < 0:
        raise ManifestError(f"cases[{index}].{field} must be a nonnegative integer")
    return value


def _validate_case_data(metric: str, data: dict[str, Any], index: int) -> None:
    if metric == "A01":
        if (
            not isinstance(data.get("disposition"), str)
            or data.get("disposition") not in DISPOSITIONS
            or not isinstance(data.get("reason"), str)
            or not data["reason"].strip()
        ):
            raise ManifestError(f"cases[{index}] needs a disposition and reason")
        if data["disposition"] in {"failed", "deferred"} and not data.get("recovery_route"):
            raise ManifestError(
                f"cases[{index}] failed/deferred disposition needs a recovery route"
            )
    elif metric == "A02":
        _need_bool(
            data, ("valuable", "retained", "essential_conditions_preserved", "critical"), index
        )
    elif metric == "A04":
        _need_bool(data, ("answerable",), index)
        for field in ("required_support_ids", "top10_eligible_ids"):
            values = data.get(field)
            if not isinstance(values, list) or any(
                not isinstance(item, str) or not item for item in values
            ):
                raise ManifestError(f"cases[{index}].{field} must be a list")
        if len(data["top10_eligible_ids"]) > 10:
            raise ManifestError(
                f"cases[{index}] may contain at most ten eligible retrieval results"
            )
        if data["answerable"] and not data["required_support_ids"]:
            raise ManifestError(f"cases[{index}] answerable retrieval task needs required support")
    elif metric == "A05":
        if (
            not isinstance(data.get("case_kind"), str)
            or data.get("case_kind") not in {"gap", "conflict"}
            or not isinstance(data.get("observed"), str)
            or data.get("observed") not in {"gap", "conflict", "answered"}
        ):
            raise ManifestError(f"cases[{index}] needs expected gap/conflict and observed outcome")
        _need_count(data, "unsupported_claims", index)
    elif metric == "A06":
        _need_bool(data, ("citation_resolves", "semantic_support"), index)
    elif metric == "A07":
        _need_bool(data, ("critical_error", "flagged"), index)
    elif metric == "A08":
        rating = data.get("usefulness_rating")
        if type(rating) is not int or not 1 <= rating <= 5:
            raise ManifestError(f"cases[{index}].usefulness_rating must be 1 through 5")
        _need_bool(data, ("ordinary_editing_only",), index)
    elif metric == "A19":
        fields = (
            "discovered_items",
            "extracted_passages",
            "supported_nonsensitive",
            "automatically_tagged",
            "automatically_resolved",
            "substantive_questions",
            "human_decisions",
            "review_seconds",
            "unsupported_or_failed",
        )
        for field in fields:
            _need_count(data, field, index)
        if data["automatically_resolved"] > data["supported_nonsensitive"]:
            raise ManifestError(f"cases[{index}] automatic resolutions exceed the denominator")
        if data["automatically_tagged"] > data["extracted_passages"]:
            raise ManifestError(f"cases[{index}] automatic tags exceed extracted passages")
        if data["supported_nonsensitive"] > data["extracted_passages"]:
            raise ManifestError(f"cases[{index}] supported passages exceed extracted passages")


def assert_no_group_overlap(manifests: Iterable[dict[str, Any]]) -> None:
    """Reject related groups or source fingerprints assigned to different splits."""
    group_splits: dict[str, str] = {}
    fingerprint_groups: dict[str, tuple[str, str]] = {}
    for manifest in manifests:
        validate_manifest(manifest)
        for group in manifest["groups"]:
            split = group["split"]
            previous = group_splits.setdefault(group["group_key"], split)
            if previous != split:
                raise ManifestError("A leakage group overlaps different evaluation splits")
            for fingerprint in group.get("source_fingerprints", []):
                group_and_split = (group["group_key"], split)
                previous = fingerprint_groups.setdefault(fingerprint, group_and_split)
                if previous != group_and_split:
                    raise ManifestError(
                        "A related source/version overlaps different groups or evaluation splits"
                    )


def score_manifest(document: dict[str, Any]) -> dict[str, Any]:
    """Score the bounded offline criteria; return aggregate counts only."""
    validate_manifest(document)
    selected_split = document["kind"]
    cases = [case for case in document["cases"] if case["split"] == selected_split]
    metrics: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        metrics[case["metric"]].append(case)

    per_metric: dict[str, Any] = {}
    for metric in sorted(METRICS):
        rows = metrics.get(metric, [])
        families = sorted(document["inventory_counts"])
        family_scores = {
            family: _score_family(
                metric,
                [r for r in rows if r["family_key"] == family],
                expected_count=document["inventory_counts"].get(family),
            )
            for family in families
        }
        per_metric[metric] = {
            "status": _gate_status(metric, rows, family_scores),
            "families": family_scores,
            "totals": _aggregate_families(family_scores),
        }
    statuses = [item["status"] for item in per_metric.values()]
    overall = "fail" if "fail" in statuses else "pending" if "pending" in statuses else "pass"
    return {
        "schema_version": 1,
        "suite_revision": document["revision"],
        "split": selected_split,
        "status": overall,
        "metrics": per_metric,
    }


def _score_family(
    metric: str, rows: list[dict[str, Any]], *, expected_count: int | None = None
) -> dict[str, Any]:
    data = [row["data"] for row in rows]
    denominator = numerator = critical_losses = critical_unflagged = 0
    if metric == "A01":
        denominator = expected_count if expected_count is not None else len(data)
        numerator = sum(
            item["disposition"] in DISPOSITIONS
            and bool(item.get("reason"))
            and (
                item["disposition"] not in {"failed", "deferred"}
                or bool(item.get("recovery_route"))
            )
            for item in data
        )
    elif metric == "A02":
        valuable = [item for item in data if item["valuable"]]
        denominator = len(valuable)
        numerator = sum(
            item["retained"] and item["essential_conditions_preserved"] for item in valuable
        )
        critical_losses = sum(
            item["critical"] and not (item["retained"] and item["essential_conditions_preserved"])
            for item in valuable
        )
    elif metric == "A04":
        answerable = [item for item in data if item["answerable"]]
        denominator = len(answerable)
        numerator = sum(
            set(item["required_support_ids"]) <= set(item["top10_eligible_ids"])
            for item in answerable
        )
    elif metric == "A05":
        denominator = len(data)
        numerator = sum(
            item["observed"] == item["case_kind"] and item["unsupported_claims"] == 0
            for item in data
        )
    elif metric == "A06":
        denominator = len(data)
        numerator = sum(item["citation_resolves"] and item["semantic_support"] for item in data)
    elif metric == "A07":
        denominator = len(data)
        numerator = sum(not item["critical_error"] or item["flagged"] for item in data)
        critical_unflagged = sum(item["critical_error"] and not item["flagged"] for item in data)
    elif metric == "A08":
        denominator = len(data)
        numerator = sum(
            item["usefulness_rating"] >= 4 and item["ordinary_editing_only"] for item in data
        )
    elif metric == "A19":
        denominator = sum(item["supported_nonsensitive"] for item in data)
        numerator = sum(item["automatically_resolved"] for item in data)
    result = {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 4) if denominator else None,
        "critical_losses": critical_losses,
        "critical_unflagged": critical_unflagged,
        "case_count": len(rows),
        "substantive_questions": sum(item.get("substantive_questions", 0) for item in data),
        "human_decisions": sum(item.get("human_decisions", 0) for item in data),
        "review_seconds": sum(item.get("review_seconds", 0) for item in data),
        "unsupported_or_failed": sum(item.get("unsupported_or_failed", 0) for item in data),
    }
    if metric == "A19":
        for field in ("discovered_items", "extracted_passages", "automatically_tagged"):
            result[field] = sum(item[field] for item in data)
    return result


def _aggregate_families(families: dict[str, dict[str, Any]]) -> dict[str, Any]:
    numerator = sum(item["numerator"] for item in families.values())
    denominator = sum(item["denominator"] for item in families.values())
    result = {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 4) if denominator else None,
        "critical_unflagged": sum(item["critical_unflagged"] for item in families.values()),
        "critical_losses": sum(item["critical_losses"] for item in families.values()),
        "case_count": sum(item["case_count"] for item in families.values()),
        "substantive_questions": sum(item["substantive_questions"] for item in families.values()),
        "human_decisions": sum(item["human_decisions"] for item in families.values()),
        "review_seconds": sum(item["review_seconds"] for item in families.values()),
        "unsupported_or_failed": sum(item["unsupported_or_failed"] for item in families.values()),
    }
    for field in ("discovered_items", "extracted_passages", "automatically_tagged"):
        if any(field in item for item in families.values()):
            result[field] = sum(item.get(field, 0) for item in families.values())
    return result


def _gate_status(
    metric: str, rows: list[dict[str, Any]], families: dict[str, dict[str, Any]]
) -> str:
    if not rows and metric != "A01":
        return "pending"
    total = _aggregate_families(families)
    if metric == "A01":
        if total["denominator"] == 0:
            return "pending"
        complete = all(
            item["numerator"] == item["denominator"] and item["case_count"] == item["denominator"]
            for item in families.values()
        )
        return "pass" if complete else "fail"
    if metric == "A02":
        if total["denominator"] < 60 or any(item["denominator"] < 20 for item in families.values()):
            return "pending"
        return "pass" if total["rate"] >= 0.95 and total["critical_losses"] == 0 else "fail"
    if metric == "A04":
        if total["denominator"] < 20:
            return "pending"
        return "pass" if total["numerator"] >= 18 else "fail"
    if metric == "A05":
        if total["case_count"] < 5:
            return "pending"
        return "pass" if total["numerator"] == total["denominator"] else "fail"
    if metric == "A06":
        return (
            "pass"
            if total["denominator"] and total["numerator"] == total["denominator"]
            else "fail"
        )
    if metric == "A07":
        if total["case_count"] < 20:
            return "pending"
        return "pass" if total["critical_unflagged"] == 0 else "fail"
    if metric == "A08":
        if total["case_count"] != 5:
            return "pending"
        return "pass" if total["numerator"] >= 4 else "fail"
    if metric == "A19":
        if (
            len(families) != 3
            or any(item["case_count"] != 1 for item in families.values())
            or total["denominator"] == 0
        ):
            return "pending"
        return "pass" if total["rate"] >= 0.8 and total["substantive_questions"] <= 10 else "fail"
    return "pending"
