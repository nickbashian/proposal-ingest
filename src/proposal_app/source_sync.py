"""Scoped, read-only source capture with resumable, conservative reconciliation."""

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.utils import timezone

from . import models as m
from .adapters import ProviderFailure
from .storage import LocalObjectStorage


@dataclass(frozen=True)
class LocalItem:
    item_id: str
    name: str
    parent_id: str | None
    path: str
    is_folder: bool
    deleted: bool
    etag: str | None
    upstream_version: str | None
    size: int | None
    is_link: bool = False


@dataclass(frozen=True)
class LocalPage:
    items: tuple[LocalItem, ...]
    next_cursor: str | None
    complete: bool


class LocalSourceAdapter:
    """Read a configured subtree; filesystem file IDs survive a same-volume rename."""

    def __init__(self, source_root: Path, *, page_size: int = 200):
        self.root = source_root.resolve(strict=True)
        if not self.root.is_dir() or page_size < 1:
            raise ValueError("A directory and positive page size are required")
        self.page_size = page_size

    def _inventory(self):
        rows = []
        pending = [self.root]
        while pending:
            directory = pending.pop()
            # pathlib.rglob may omit unreadable subtrees; every directory error
            # must abort reconciliation so absence cannot imply deletion.
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    relative = path.relative_to(self.root).as_posix()
                    info = path.lstat()
                    rows.append((relative, path, info))
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(path)
        rows.sort(key=lambda row: row[0])
        fingerprint = hashlib.sha256()
        for relative, _, info in rows:
            fingerprint.update(
                json.dumps(
                    [relative, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns],
                    separators=(",", ":"),
                ).encode("utf-8")
            )
        return rows, fingerprint.hexdigest()

    def delta_page(self, root_item_id: str, cursor: str | None = None) -> LocalPage:
        if root_item_id != str(self.root):
            raise ProviderFailure("scope_mismatch")
        try:
            rows, signature = self._inventory()
        except OSError as exc:
            raise ProviderFailure("source_unavailable", retryable=True) from exc
        after = ""
        if cursor:
            try:
                token = json.loads(cursor)
                if token["signature"] != signature or not isinstance(token["after"], str):
                    raise ValueError
                after = token["after"]
            except (ValueError, KeyError, TypeError) as exc:
                raise ProviderFailure("checkpoint_expired", retryable=True) from exc
        selected = [row for row in rows if row[0] > after][: self.page_size]
        items = []
        for relative, path, info in selected:
            is_folder = path.is_dir() and not path.is_symlink()
            item_id = f"{info.st_dev}:{info.st_ino}"
            parent = path.parent
            parent_info = parent.lstat()
            items.append(
                LocalItem(
                    item_id=item_id,
                    name=path.name,
                    parent_id=f"{parent_info.st_dev}:{parent_info.st_ino}",
                    path=relative,
                    is_folder=is_folder,
                    deleted=False,
                    etag=f"{info.st_mtime_ns}:{info.st_size}",
                    upstream_version=f"{info.st_mtime_ns}:{info.st_size}",
                    size=None if is_folder else info.st_size,
                    is_link=path.is_symlink(),
                )
            )
        complete = len([row for row in rows if row[0] > after]) <= len(selected)
        next_cursor = (
            None
            if complete
            else json.dumps(
                {"signature": signature, "after": selected[-1][0]}, separators=(",", ":")
            )
        )
        return LocalPage(tuple(items), next_cursor, complete)

    def download_verified(self, item: LocalItem) -> bytes:
        path = (self.root / item.path).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise ProviderFailure("source_unavailable", retryable=True)
        for _ in range(2):
            try:
                flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(path, flags)
                with os.fdopen(descriptor, "rb") as stream:
                    before = os.fstat(stream.fileno())
                    if (
                        not stat.S_ISREG(before.st_mode)
                        or f"{before.st_dev}:{before.st_ino}" != item.item_id
                    ):
                        raise ProviderFailure("inconsistent_snapshot", retryable=True)
                    content = stream.read((item.size or 0) + 1)
                    after = os.fstat(stream.fileno())
            except OSError as exc:
                raise ProviderFailure("source_unavailable", retryable=True) from exc
            if (
                before.st_ino == after.st_ino
                and before.st_dev == after.st_dev
                and before.st_size == after.st_size == len(content) == item.size
                and before.st_mtime_ns == after.st_mtime_ns
                and f"{after.st_mtime_ns}:{after.st_size}" == item.etag
            ):
                return content
        raise ProviderFailure("inconsistent_snapshot", retryable=True)


def disposition(item):
    """Every observed item gets an explicit capture or processing state."""
    name = item.name.casefold()
    components = item.path.replace("\\", "/").casefold().split("/")
    if (
        getattr(item, "is_link", False)
        or any(component.startswith((".", "~$")) for component in components if component)
        or name in {"thumbs.db", "desktop.ini"}
    ):
        return "administrative_exclusion", "hidden_or_temporary"
    if item.is_folder:
        return "container", "folder"
    extension = Path(name).suffix
    if extension in {".zip", ".7z", ".rar"}:
        return "awaiting_conversion", "archive"
    if extension in {".eml", ".msg", ".pst"}:
        return "awaiting_conversion", "email"
    if extension in {".doc", ".xls", ".ppt", ".rtf"}:
        return "awaiting_conversion", "legacy_format"
    if extension in {".pdf", ".docx", ".xlsx", ".pptx", ".csv", ".txt", ".md"}:
        return "awaiting_extraction", "supported_format"
    return "inventory_only", "unsupported_format"


def work_fingerprint(stage: str, *, source_digest: str, revisions: dict[str, str]) -> str:
    """Version exactly the inputs used by a downstream stage."""
    dependencies = {
        "extract": ("extractor", "schema"),
        "classify": ("extractor", "model", "prompt", "schema", "policy"),
        "publish": ("extractor", "schema", "policy"),
    }
    if stage not in dependencies or len(source_digest) != 64:
        raise ValueError("Unknown stage or source digest")
    needed = dependencies[stage]
    if any(not revisions.get(key) for key in needed):
        raise ValueError("Missing work revision")
    payload = [stage, source_digest, [(key, revisions[key]) for key in needed]]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def _record_item(run, item, snapshot):
    scope = run.scope
    display_path = (
        f"{scope.year}/{Path(scope.root_item).name}/{item.path}"
        if scope.connector == "local"
        else item.path
    )
    identity = {
        "connector": scope.connector,
        "tenant": scope.tenant,
        "site": scope.site,
        "drive": scope.drive,
        "item": item.item_id,
    }
    state, reason = disposition(item)
    source, _ = m.SourceItem.objects.get_or_create(
        **identity,
        defaults={
            "collection": scope.collection,
            "display_path": display_path,
            "disposition": "awaiting_decision",
            "disposition_reason": "source_captured_pending_review",
        },
    )
    if source.collection_id != scope.collection_id:
        raise PermissionDenied("Source identity belongs to another collection")
    if source.display_path != display_path:
        source.display_path = display_path
        source.save(update_fields=["display_path"])
    presence, _ = m.SourcePresence.objects.update_or_create(
        scope=scope,
        source=source,
        defaults={
            "last_seen_run": run,
            "observed_at": timezone.now(),
            "retired_at": None,
            "display_path": display_path,
            "disposition": state,
            "reason": reason,
        },
    )
    m.SourcePathEvent.objects.create(run=run, source=source, scope=scope, display_path=display_path)
    family, _ = m.VersionFamily.objects.get_or_create(proposal=scope.proposal, key="source")
    m.ProposalMembership.objects.get_or_create(source=source, family=family)
    if snapshot is None:
        return presence, False
    digest, size, key = snapshot
    blob, _ = m.ContentBlob.objects.get_or_create(
        sha256=digest, defaults={"size": size, "storage_key": key}
    )
    if blob.size != size:
        raise ValueError("Content hash size collision")
    if not blob.storage_key:
        blob.storage_key = key
        blob.save(update_fields=["storage_key"])
    observation_key = hashlib.sha256(
        json.dumps([item.upstream_version, item.etag, digest], separators=(",", ":")).encode()
    ).hexdigest()
    version, created = m.SourceVersion.objects.get_or_create(
        source=source,
        observation_key=observation_key,
        defaults={
            "blob": blob,
            "upstream_version": item.upstream_version,
            "etag": item.etag,
            "observed_path": display_path,
        },
    )
    if version.blob_id != blob.id or version.etag != item.etag:
        raise ValueError("Observation identity cannot be rewritten")
    return presence, created


def _reusable_version(scope, item):
    # A local mtime/size pair can be preserved while bytes change. Only the
    # provider's version contract may skip a content read.
    if scope.connector == "local" or not item.upstream_version or item.size is None:
        return False
    source = m.SourceItem.objects.filter(
        connector=scope.connector,
        tenant=scope.tenant,
        site=scope.site,
        drive=scope.drive,
        item=item.item_id,
        collection=scope.collection,
    ).first()
    if source is None:
        return False
    version = (
        m.SourceVersion.objects.filter(
            source=source, etag=item.etag, upstream_version=item.upstream_version
        )
        .select_related("blob")
        .order_by("-observed_at")
        .first()
    )
    if version is None or version.blob.size != item.size or not version.blob.storage_key:
        return False
    try:
        LocalObjectStorage(settings.LOCAL_STORAGE_ROOT).get(version.blob.storage_key)
    except (OSError, ValueError):
        return False
    return True


def _scope_lock(scope_id):
    # Session advisory lock fences two command processes without holding a network transaction.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(hashtext(%s))", [str(scope_id)])
        if not cursor.fetchone()[0]:
            raise ProviderFailure("sync_already_running", retryable=True)


def _scope_unlock(scope_id):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_unlock(hashtext(%s))", [str(scope_id)])


def sync_scope(scope: m.SourceScope, adapter, *, max_snapshot_bytes: int | None = None):
    """Resume an interrupted full crawl and retire only after a complete clean pass."""
    if scope.proposal.collection_id != scope.collection_id:
        raise ValueError("Scope proposal belongs to another collection")
    if scope.connector == "local" and settings.LOCAL_STORAGE_ROOT.resolve().is_relative_to(
        Path(scope.root_item).resolve()
    ):
        raise ValueError("Snapshot output must be outside the read-only source root")
    if max_snapshot_bytes is None:
        max_snapshot_bytes = settings.APP["max_snapshot_bytes"]
    _scope_lock(scope.id)
    try:
        with transaction.atomic():
            m.SourceScope.objects.select_for_update().get(pk=scope.pk)
            run = m.SourceSyncRun.objects.filter(scope=scope, state="running").first()
            if run is None:
                run = m.SourceSyncRun.objects.create(
                    scope=scope,
                    counts={"seen": 0, "snapshots": 0, "reused": 0, "issues": 0, "retired": 0},
                )
        restarts = 0
        storage = LocalObjectStorage(
            settings.LOCAL_STORAGE_ROOT, require_durable=settings.MODE == "production"
        )
        while True:
            try:
                page = adapter.delta_page(scope.root_item, run.cursor or None)
            except ProviderFailure as exc:
                if exc.code == "checkpoint_expired" and run.cursor and restarts < 2:
                    restarts += 1
                    with transaction.atomic():
                        run.state = "incomplete"
                        run.error_code = "checkpoint_expired"
                        run.save(update_fields=["state", "error_code"])
                        run = m.SourceSyncRun.objects.create(
                            scope=scope,
                            counts={
                                "seen": 0,
                                "snapshots": 0,
                                "reused": 0,
                                "issues": 0,
                                "retired": 0,
                            },
                        )
                    continue
                if exc.code == "checkpoint_expired":
                    run.state = "incomplete"
                    run.error_code = exc.code
                    run.save(update_fields=["state", "error_code"])
                    return run
                run.error_code = exc.code
                run.save(update_fields=["error_code"])
                return run
            if not page.complete and not page.next_cursor:
                raise ValueError("Incomplete page needs a cursor")
            issues = []
            prepared: list[tuple[Any, tuple[str, int, str] | None, bool]] = []
            for item in page.items:
                if item.deleted:
                    # A full enumeration reconciles deleted items at completion.
                    continue
                if scope.connector == "sharepoint":
                    try:
                        item = adapter.resolve_scoped_item(item, year=scope.year)
                    except ProviderFailure as exc:
                        issues.append((item, exc.code))
                        continue
                state, _ = disposition(item)
                if (
                    item.is_folder
                    or state == "administrative_exclusion"
                    or not getattr(item, "is_file", True)
                ):
                    prepared.append((item, None, False))
                    continue
                if item.size is not None and item.size > max_snapshot_bytes:
                    issues.append((item, "snapshot_size_limit"))
                    prepared.append((item, None, False))
                    continue
                if _reusable_version(scope, item):
                    prepared.append((item, None, True))
                    continue
                try:
                    content = adapter.download_verified(item)
                    digest = hashlib.sha256(content).hexdigest()
                    key = storage.put_immutable(digest, content)
                    prepared.append((item, (digest, len(content), key), False))
                    del content
                except ProviderFailure as exc:
                    issues.append((item, exc.code))
                    prepared.append((item, None, False))
            with transaction.atomic():
                for item, snapshot, reused in prepared:
                    _, created_version = _record_item(run, item, snapshot)
                    run.counts["seen"] += 1
                    run.counts["snapshots"] += int(created_version)
                    run.counts["reused"] += int(
                        reused or (snapshot is not None and not created_version)
                    )
                for item, code in issues:
                    m.SourceCaptureIssue.objects.create(
                        run=run, source_item=item.item_id, code=code
                    )
                run.counts["issues"] += len(issues)
                run.cursor = page.next_cursor or ""
                run.error_code = ""
                run.save(update_fields=["cursor", "counts", "error_code"])
                if page.complete:
                    if run.counts["issues"]:
                        run.state = "incomplete"
                        run.error_code = "capture_issues"
                    else:
                        run.counts["retired"] = (
                            m.SourcePresence.objects.filter(scope=scope, retired_at__isnull=True)
                            .exclude(last_seen_run=run)
                            .update(
                                retired_at=timezone.now(),
                                disposition="retired",
                                reason="authoritative_reconciliation",
                            )
                        )
                        run.state = "completed"
                        run.completed_at = timezone.now()
                    run.save(update_fields=["state", "error_code", "completed_at", "counts"])
            if page.complete:
                return run
    finally:
        _scope_unlock(scope.id)
