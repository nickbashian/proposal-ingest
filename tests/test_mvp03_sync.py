"""MVP-03 local capture, reconciliation, and selective work contracts."""

import hashlib
import pytest
from django.core.management import CommandError, call_command

from proposal_app import models as m
from proposal_app.adapters import ProviderFailure
from proposal_app.source_sync import LocalSourceAdapter, sync_scope, work_fingerprint
from proposal_app.storage import LocalObjectStorage

pytestmark = pytest.mark.django_db


def make_scope(tmp_path, *, collection=None, drive="local-volume", proposal="P1"):
    root = tmp_path / proposal
    root.mkdir(exist_ok=True)
    collection = collection or m.Collection.objects.create(name="MVP03 collection")
    proposal_row, _ = m.Proposal.objects.get_or_create(collection=collection, identifier=proposal)
    scope = m.SourceScope.objects.create(
        collection=collection,
        connector="local",
        tenant="local",
        site="local",
        drive=drive,
        root_item=str(root.resolve()),
        proposal=proposal_row,
        year=2025,
    )
    return root, scope


def test_local_dispositions_capture_and_reuse(tmp_path, settings):
    settings.LOCAL_STORAGE_ROOT = tmp_path / "objects"
    root, scope = make_scope(tmp_path)
    (root / "study.pdf").write_bytes(b"synthetic result")
    (root / "archive.zip").write_bytes(b"synthetic zip marker")
    (root / "mail.msg").write_bytes(b"synthetic email marker")
    (root / "old.doc").write_bytes(b"synthetic legacy marker")
    (root / ".private").write_bytes(b"synthetic admin marker")
    (root / "subfolder").mkdir()
    first = sync_scope(scope, LocalSourceAdapter(root, page_size=2))
    assert first.state == "completed"
    assert first.counts == {"seen": 6, "snapshots": 4, "reused": 0, "issues": 0, "retired": 0}
    assert set(m.SourcePresence.objects.values_list("disposition", flat=True)) == {
        "container",
        "administrative_exclusion",
        "awaiting_conversion",
        "awaiting_extraction",
    }
    assert m.SourceVersion.objects.count() == 4
    second = sync_scope(scope, LocalSourceAdapter(root, page_size=2))
    assert second.counts["reused"] == 4
    assert m.SourceVersion.objects.count() == 4
    for version in m.SourceVersion.objects.select_related("blob"):
        assert LocalObjectStorage(settings.LOCAL_STORAGE_ROOT).get(version.blob.storage_key)


def test_rename_move_and_identical_bytes_keep_identity_and_memberships(tmp_path, settings):
    settings.LOCAL_STORAGE_ROOT = tmp_path / "objects"
    first_root, first_scope = make_scope(tmp_path)
    second_root, second_scope = make_scope(
        tmp_path, collection=first_scope.collection, proposal="P2"
    )
    first_path = first_root / "first.pdf"
    first_path.write_bytes(b"same synthetic bytes")
    sync_scope(first_scope, LocalSourceAdapter(first_root))
    source = m.SourceItem.objects.get(display_path="2025/P1/first.pdf")
    first_path.rename(first_root / "renamed.pdf")
    sync_scope(first_scope, LocalSourceAdapter(first_root))
    source.refresh_from_db()
    assert source.display_path == "2025/P1/renamed.pdf"
    assert m.SourceItem.objects.count() == 1
    (first_root / "renamed.pdf").rename(second_root / "moved.pdf")
    sync_scope(second_scope, LocalSourceAdapter(second_root))
    sync_scope(first_scope, LocalSourceAdapter(first_root))
    assert m.SourceItem.objects.count() == 1
    assert m.ProposalMembership.objects.count() == 2
    assert m.SourcePresence.objects.get(scope=first_scope).retired_at is not None
    assert m.SourcePresence.objects.get(scope=second_scope).retired_at is None
    (first_root / "copy.pdf").write_bytes(b"same synthetic bytes")
    sync_scope(first_scope, LocalSourceAdapter(first_root))
    assert m.SourceItem.objects.count() == 2
    assert m.ContentBlob.objects.count() == 1


def test_changed_bytes_create_version_and_removal_requires_complete_crawl(tmp_path, settings):
    settings.LOCAL_STORAGE_ROOT = tmp_path / "objects"
    root, scope = make_scope(tmp_path)
    path = root / "result.pdf"
    path.write_bytes(b"before")
    sync_scope(scope, LocalSourceAdapter(root))
    path.write_bytes(b"after")
    sync_scope(scope, LocalSourceAdapter(root))
    assert m.SourceVersion.objects.count() == 2

    class Interrupted:
        def delta_page(self, root_item_id, cursor=None):
            raise ProviderFailure("graph_network", retryable=True)

    interrupted = sync_scope(scope, Interrupted())
    assert interrupted.state == "running"
    path.unlink()
    assert m.SourcePresence.objects.get(scope=scope).retired_at is None
    recovered = sync_scope(scope, LocalSourceAdapter(root))
    assert recovered.state == "completed"
    assert m.SourcePresence.objects.get(scope=scope).retired_at is not None


def test_expired_checkpoint_restarts_without_false_retirement(tmp_path, settings):
    settings.LOCAL_STORAGE_ROOT = tmp_path / "objects"
    root, scope = make_scope(tmp_path)
    (root / "one.pdf").write_bytes(b"one")
    (root / "two.pdf").write_bytes(b"two")
    initial = sync_scope(scope, LocalSourceAdapter(root, page_size=1))
    assert initial.state == "completed"
    m.SourceSyncRun.objects.create(scope=scope, cursor='{"signature":"bad","after":"one.pdf"}')
    recovered = sync_scope(scope, LocalSourceAdapter(root, page_size=1))
    assert recovered.state == "completed"
    assert m.SourceSyncRun.objects.filter(
        scope=scope, state="incomplete", error_code="checkpoint_expired"
    ).exists()
    assert not m.SourcePresence.objects.filter(scope=scope, retired_at__isnull=False).exists()


def test_inconsistent_download_does_not_create_verified_snapshot_or_retire(tmp_path, settings):
    settings.LOCAL_STORAGE_ROOT = tmp_path / "objects"
    root, scope = make_scope(tmp_path)
    (root / "good.pdf").write_bytes(b"good")
    (root / "bad.pdf").write_bytes(b"bad")
    real = LocalSourceAdapter(root)

    class Racing:
        def delta_page(self, root_item_id, cursor=None):
            return real.delta_page(root_item_id, cursor)

        def download_verified(self, item):
            if item.name == "bad.pdf":
                raise ProviderFailure("inconsistent_snapshot", retryable=True)
            return real.download_verified(item)

    run = sync_scope(scope, Racing())
    assert run.state == "incomplete"
    assert run.counts["seen"] == 2
    assert m.SourceVersion.objects.count() == 1
    assert m.SourceCaptureIssue.objects.get(run=run).code == "inconsistent_snapshot"
    assert sync_scope(scope, real).state == "completed"
    assert m.SourceVersion.objects.count() == 2


def test_per_scope_failure_does_not_block_other_proposal(tmp_path, settings):
    settings.LOCAL_STORAGE_ROOT = tmp_path / "objects"
    failed_root, failed_scope = make_scope(tmp_path)
    okay_root, okay_scope = make_scope(tmp_path, collection=failed_scope.collection, proposal="P2")
    (failed_root / "bad.pdf").write_bytes(b"bad")
    (okay_root / "good.pdf").write_bytes(b"good")

    class Denied:
        def delta_page(self, root_item_id, cursor=None):
            raise ProviderFailure("denied")

    assert sync_scope(failed_scope, Denied()).state == "running"
    assert sync_scope(okay_scope, LocalSourceAdapter(okay_root)).state == "completed"
    assert m.SourceVersion.objects.count() == 1


def test_work_fingerprint_selective_invalidation():
    digest = hashlib.sha256(b"synthetic").hexdigest()
    revisions = dict(extractor="x1", model="m1", prompt="p1", schema="s1", policy="r1")
    base = {
        stage: work_fingerprint(stage, source_digest=digest, revisions=revisions)
        for stage in ("extract", "classify", "publish")
    }
    changed = {**revisions, "model": "m2"}
    assert work_fingerprint("extract", source_digest=digest, revisions=changed) == base["extract"]
    assert work_fingerprint("classify", source_digest=digest, revisions=changed) != base["classify"]
    assert work_fingerprint("publish", source_digest=digest, revisions=changed) == base["publish"]
    changed["policy"] = "r2"
    assert work_fingerprint("publish", source_digest=digest, revisions=changed) != base["publish"]


def test_local_sync_command_enforces_2025_folder_membership(tmp_path, settings):
    settings.LOCAL_STORAGE_ROOT = tmp_path / "objects"
    collection = m.Collection.objects.create(name="Command collection")
    wrong = tmp_path / "Proposal A"
    wrong.mkdir()
    with pytest.raises(CommandError, match="year folder"):
        call_command(
            "sync_sources",
            collection=str(collection.id),
            proposal="Proposal A",
            year=2025,
            connector="local",
            root=str(wrong),
        )
    root = tmp_path / "2025" / "Proposal A"
    root.mkdir(parents=True)
    (root / "history-2026.pdf").write_bytes(b"associated later history")
    call_command(
        "sync_sources",
        collection=str(collection.id),
        proposal="Proposal A",
        year=2025,
        connector="local",
        root=str(root),
    )
    assert m.SourceSyncRun.objects.get().state == "completed"
    assert m.SourcePresence.objects.get().display_path == "2025/Proposal A/history-2026.pdf"
