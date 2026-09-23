"""Validate and stage prototype exports without granting collection eligibility.

Legacy document IDs are content-derived. They are never used as source identities:
an import maps a row only when its location, proposal membership, and bytes agree
with a captured source version in the application database.
"""

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db import transaction
from pydantic import ValidationError

from proposal_ingest.scanner import INVENTORY_COLUMNS
from proposal_ingest.schemas import APP_SCHEMA_VERSION, DocumentMetadata, InventoryRecord

from . import models as m, services
from .storage import LocalObjectStorage

MAX_EXPORT_BYTES = 25_000_000


@dataclass(frozen=True)
class LegacyExport:
    name: str
    content: bytes

    @classmethod
    def read(cls, path: Path, name: str):
        if path.stat().st_size > MAX_EXPORT_BYTES:
            raise ValueError(f"{name} export exceeds the size limit")
        return cls(name, path.read_bytes())


def _path(value):
    """Comparison key only; never resolve an imported absolute path on disk."""
    return "/".join(part for part in value.replace("\\", "/").casefold().split("/") if part)


def _rows(export):
    if export is None:
        return []
    try:
        raw = export.content.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError(f"{export.name} must be UTF-8") from exc
    if export.name.endswith(".csv"):
        return list(csv.DictReader(io.StringIO(raw, newline="")))
    if export.name.endswith(".jsonl"):
        result = []
        for number, line in enumerate(raw.splitlines(), 1):
            if line.strip():
                try:
                    result.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{export.name} line {number} is invalid JSON") from exc
        return result
    raise ValueError(f"Unsupported export type: {export.name}")


def _identity_map(collection, records):
    """Return uniquely evidenced mappings and stable quarantine codes."""
    paths = {}
    scoped_paths = {}
    for source in m.SourceItem.objects.filter(collection=collection).iterator():
        paths[source.id] = {_path(source.display_path)}
    for event in m.SourcePathEvent.objects.filter(scope__collection=collection).select_related(
        "scope"
    ):
        normalized = _path(event.display_path)
        paths.setdefault(event.source_id, set()).add(normalized)
        scoped_paths.setdefault(event.source_id, set()).add(
            (normalized, str(event.scope.year), event.scope.proposal_id)
        )
    versions = list(
        m.SourceVersion.objects.filter(source__collection=collection)
        .select_related("source", "blob")
        .prefetch_related("source__proposalmembership_set__family__proposal")
    )
    by_digest = {}
    latest_by_source = {}
    for version in versions:
        by_digest.setdefault(version.blob.sha256, []).append(version)
        previous = latest_by_source.get(version.source_id)
        if previous is None or (version.observed_at, str(version.id)) > (
            previous.observed_at,
            str(previous.id),
        ):
            latest_by_source[version.source_id] = version
    accepted, rejected, seen = {}, {}, {}
    for position, raw in enumerate(records, 1):
        try:
            record = InventoryRecord.model_validate(raw)
        except (ValidationError, TypeError, ValueError):
            rejected[f"row:{position}"] = "invalid_inventory_schema"
            continue
        old_id = record.document_id
        if old_id is not None and old_id in seen:
            accepted.pop(old_id, None)
            rejected[old_id] = "duplicate_legacy_id"
            rejected[f"row:{position}"] = "duplicate_legacy_id"
            continue
        seen[old_id] = position
        if record.year_folder != "2025":
            rejected[old_id] = "outside_2025_folder"
            continue
        if not record.relative_path or not record.proposal_branch:
            rejected[old_id] = "missing_scope"
            continue
        relative = _path(record.relative_path)
        if not relative.startswith("2025/") or not _path(record.source_path).endswith(relative):
            rejected[old_id] = "inconsistent_inventory_path"
            continue
        parts = relative.split("/")
        if len(parts) < 3 or parts[1] != _path(record.proposal_branch):
            rejected[old_id] = "inconsistent_inventory_scope"
            continue
        matches = {}
        for version in by_digest.get(record.sha256, []):
            source_paths = paths[version.source_id]
            if not any(
                source_path == relative or source_path.endswith("/" + relative)
                for source_path in source_paths
            ):
                continue
            memberships = version.source.proposalmembership_set.all()
            legacy_membership = any(
                member.family.proposal.identifier == record.proposal_id
                or member.family.key.casefold() == record.proposal_branch.casefold()
                for member in memberships
            )
            captured_scope = any(
                path.endswith(relative)
                and year == record.year_folder
                and any(member.family.proposal_id == proposal_id for member in memberships)
                for path, year, proposal_id in scoped_paths.get(version.source_id, set())
            )
            if not (legacy_membership or captured_scope):
                continue
            previous = matches.get(version.source_id)
            if previous is None or (version.observed_at, str(version.id)) > (
                previous.observed_at,
                str(previous.id),
            ):
                matches[version.source_id] = version
        if len(matches) != 1:
            rejected[old_id] = "source_unresolved" if not matches else "source_collision"
            continue
        version = next(iter(matches.values()))
        accepted[old_id] = {
            "source_id": str(version.source_id),
            "source_version_id": str(version.id),
            "sha256": version.blob.sha256,
            "proposal_id": record.proposal_id,
            "source_path": _path(record.source_path),
            "current": version.id == latest_by_source[version.source_id].id,
        }
    return accepted, rejected


def _metadata_report(rows, mapping):
    accepted, quarantined, accepted_keys, seen = 0, {}, set(), set()
    for position, raw in enumerate(rows, 1):
        old_id = raw.get("document_id") if isinstance(raw, dict) else None
        key = old_id or f"row:{position}"
        if old_id and old_id in seen:
            if old_id in accepted_keys:
                accepted -= 1
                accepted_keys.remove(old_id)
            quarantined[key] = "duplicate_metadata_id"
            quarantined[f"row:{position}"] = "duplicate_metadata_id"
            continue
        if old_id:
            seen.add(old_id)
        try:
            item = DocumentMetadata.model_validate(raw)
        except (ValidationError, TypeError, ValueError):
            quarantined[key] = "invalid_metadata_schema"
            continue
        if "schema_version" not in raw or item.schema_version != APP_SCHEMA_VERSION:
            quarantined[key] = "unsupported_metadata_schema_version"
        elif old_id not in mapping:
            quarantined[key] = "source_unresolved"
        elif (
            item.system.sha256 != mapping[old_id]["sha256"]
            or item.proposal_id != mapping[old_id]["proposal_id"]
            or _path(item.system.source_path) != mapping[old_id]["source_path"]
        ):
            quarantined[key] = "metadata_scope_or_bytes_changed"
        else:
            # Metadata is historical lineage, never a current eligibility decision.
            accepted += 1
            accepted_keys.add(key)
    return accepted, quarantined


def _answer_report(rows, mapping):
    accepted, quarantined, accepted_keys, seen = 0, {}, set(), set()
    for position, row in enumerate(rows, 1):
        key = (
            row.get("question_id")
            if isinstance(row, dict) and isinstance(row.get("question_id"), str)
            else None
        ) or f"row:{position}"
        required = (
            "question_id",
            "document_id",
            "proposal_id",
            "source_path",
            "field",
            "user_answer",
        )
        if (
            not isinstance(row, dict)
            or None in row
            or any(not isinstance(row.get(field), str) for field in required)
        ):
            quarantined[key] = "invalid_answer_row"
            continue
        if not row.get("user_answer", "").strip():
            continue
        if key in seen:
            if key in accepted_keys:
                accepted -= 1
                accepted_keys.remove(key)
            quarantined[key] = "duplicate_question_id"
            quarantined[f"row:{position}"] = "duplicate_question_id"
            continue
        seen.add(key)
        old_id = row.get("document_id", "")
        if old_id not in mapping:
            quarantined[key] = "source_unresolved"
        elif row.get("field") in {"include_in_clean_set", "include_in_future_rag"}:
            # A document-wide boolean cannot express a partial passage treatment.
            quarantined[key] = "inclusion_requires_current_review"
        elif (
            row.get("scope") != "document"
            or row.get("proposal_id") != mapping[old_id]["proposal_id"]
        ):
            quarantined[key] = "answer_scope_unverified"
        elif _path(row.get("source_path", "")) != mapping[old_id]["source_path"]:
            quarantined[key] = "answer_source_changed"
        elif not mapping[old_id]["current"]:
            quarantined[key] = "stale_source_version"
        elif (
            not isinstance(row.get("evidence_summary"), str) or not row["evidence_summary"].strip()
        ):
            quarantined[key] = "answer_evidence_unverified"
        else:
            # Still staged as historical evidence; no DecisionEvent is created.
            accepted += 1
            accepted_keys.add(key)
    return accepted, quarantined


def _validate_headers(inventory, answers):
    if inventory.name.endswith(".csv"):
        headers = next(csv.reader(io.StringIO(inventory.content.decode("utf-8-sig"))), [])
        if headers != INVENTORY_COLUMNS:
            raise ValueError("Inventory CSV columns do not match the prototype schema")
    if answers is not None:
        if not answers.name.endswith(".csv"):
            raise ValueError("Answers must be a CSV export")
        headers = next(csv.reader(io.StringIO(answers.content.decode("utf-8-sig"))), [])
        required = {
            "question_id",
            "proposal_id",
            "document_id",
            "source_path",
            "field",
            "user_answer",
        }
        if len(headers) != len(set(headers)) or not required.issubset(headers):
            raise ValueError("Answers CSV columns do not match the prototype schema")


def prepare_legacy_import(user, collection_id, *, inventory, metadata=None, answers=None):
    """Read and report a bundle; never write on this path."""
    services.authorize(user, collection_id)
    collection = m.Collection.objects.get(pk=collection_id)
    exports = [LegacyExport.read(Path(inventory), Path(inventory).name)]
    if metadata is not None:
        exports.append(LegacyExport.read(Path(metadata), Path(metadata).name))
    if answers is not None:
        exports.append(LegacyExport.read(Path(answers), Path(answers).name))
    if len({item.name for item in exports}) != len(exports):
        raise ValueError("Export file names must be distinct")
    _validate_headers(exports[0], exports[-1] if answers is not None else None)
    if not exports[0].name.endswith((".csv", ".jsonl")):
        raise ValueError("Inventory must be CSV or JSONL")
    if metadata is not None and not exports[1].name.endswith(".jsonl"):
        raise ValueError("Metadata must be JSONL")
    inventory_rows = _rows(exports[0])
    mappings, inventory_quarantine = _identity_map(collection, inventory_rows)
    metadata_rows = _rows(exports[1]) if metadata is not None else []
    answer_rows = _rows(exports[-1]) if answers is not None else []
    metadata_accepted, metadata_quarantine = _metadata_report(metadata_rows, mappings)
    answer_accepted, answer_quarantine = _answer_report(answer_rows, mappings)
    hasher = hashlib.sha256()
    for export in sorted(exports, key=lambda item: item.name):
        hasher.update(export.name.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(hashlib.sha256(export.content).digest())
    report = {
        "bundle_sha256": hasher.hexdigest(),
        "inventory": {"accepted": len(mappings), "quarantined": len(inventory_quarantine)},
        "metadata": {"accepted": metadata_accepted, "quarantined": len(metadata_quarantine)},
        "answers": {"accepted": answer_accepted, "quarantined": len(answer_quarantine)},
        "identity_map": mappings,
        "quarantine": {
            "inventory": inventory_quarantine,
            "metadata": metadata_quarantine,
            "answers": answer_quarantine,
        },
        "original_exports": {
            item.name: hashlib.sha256(item.content).hexdigest() for item in exports
        },
        "policy": "historical_lineage_only",
    }
    return report, exports


@transaction.atomic
def commit_legacy_import(user, collection_id, *, inventory, metadata=None, answers=None):
    """Persist exact originals and the validated report once per collection/bundle."""
    report, exports = prepare_legacy_import(
        user, collection_id, inventory=inventory, metadata=metadata, answers=answers
    )
    existing = m.LegacyImport.objects.filter(
        collection_id=collection_id, sha256=report["bundle_sha256"]
    ).first()
    if existing is not None:
        return existing, False
    storage = LocalObjectStorage(
        settings.LOCAL_STORAGE_ROOT, require_durable=settings.MODE == "production"
    )
    for export in exports:
        digest = report["original_exports"][export.name]
        storage.put_immutable(digest, export.content)
    result, created = m.LegacyImport.objects.get_or_create(
        collection_id=collection_id,
        sha256=report["bundle_sha256"],
        defaults={"records": report},
    )
    return result, created
