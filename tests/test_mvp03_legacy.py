"""Legacy exports are lineage, never current publication permission."""

import csv
import hashlib
import io
import json

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command

from proposal_app import legacy_import, models as m, services
from proposal_app.storage import LocalObjectStorage
from proposal_app.source_sync import LocalSourceAdapter, sync_scope
from proposal_ingest.question_loop import REVIEW_COLUMNS
from proposal_ingest.scanner import INVENTORY_COLUMNS, scan_source_root
from proposal_ingest.mock_bedrock import analyze_document_mock
from proposal_ingest.schemas import InventoryRecord

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(settings, tmp_path):
    settings.LOCAL_STORAGE_ROOT = tmp_path / "objects"
    user = get_user_model().objects.create_user(username="legacy-owner")
    m.Identity.objects.create(user=user, issuer="local", subject="legacy-owner", allowed=True)
    collection = m.Collection.objects.create(name="Legacy collection")
    m.CollectionAccess.objects.create(user=user, collection=collection)
    return user, collection


def _csv_bytes(columns, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _inventory(path, content, old_id="doc_old", proposal="legacy-proposal"):
    relative = f"2025/Proposal A/{path}"
    return {
        "document_id": old_id,
        "proposal_id": proposal,
        "source_path": "C:/archive/" + relative,
        "relative_path": relative,
        "year_folder": "2025",
        "proposal_branch": "Proposal A",
        "file_name_original": path,
        "file_name_safe": path,
        "extension": ".txt",
        "size_bytes": len(content),
        "modified_time": "2025-06-01T00:00:00Z",
        "sha256": hashlib.sha256(content).hexdigest(),
        "eligible_for_processing": True,
        "processing_strategy": "local_extract_then_bedrock",
        "processing_status": "pending_analysis",
        "skip_reason": None,
        "duplicate_of_document_id": None,
        "superseded_by_document_id": None,
    }


def _capture(user, collection, path, content, item):
    return services.observe_source(
        user,
        collection.id,
        identity={
            "collection_id": collection.id,
            "connector": "local",
            "tenant": "local",
            "site": "fixture",
            "drive": "2025",
            "item": item,
        },
        path=f"C:/archive/2025/Proposal A/{path}",
        observation_key="v1",
        content=content,
        proposal="legacy-proposal",
        family="Proposal A",
    )


def test_dry_run_maps_location_and_bytes_without_writing(owner, tmp_path):
    user, collection = owner
    first = _capture(user, collection, "A.txt", b"same", "a")
    second = _capture(user, collection, "B.txt", b"same", "b")
    path = tmp_path / "file_inventory.csv"
    path.write_bytes(
        _csv_bytes(
            INVENTORY_COLUMNS,
            [_inventory("A.txt", b"same", "old-a"), _inventory("B.txt", b"same", "old-b")],
        )
    )
    report, _ = legacy_import.prepare_legacy_import(user, collection.id, inventory=path)
    assert report["inventory"] == {"accepted": 2, "quarantined": 0}
    assert report["identity_map"]["old-a"]["source_version_id"] == str(first.id)
    assert report["identity_map"]["old-b"]["source_version_id"] == str(second.id)
    assert first.blob_id == second.blob_id
    assert not m.LegacyImport.objects.exists()


def test_import_maps_actual_scoped_sync_and_retained_move_history(owner, tmp_path):
    user, collection = owner
    source_root = tmp_path / "source"
    root = source_root / "2025" / "Proposal A"
    root.mkdir(parents=True)
    path = root / "A.txt"
    path.write_bytes(b"synthetic lineage")
    proposal = m.Proposal.objects.create(collection=collection, identifier="Proposal A")
    scope = m.SourceScope.objects.create(
        collection=collection,
        connector="local",
        tenant="local",
        site="local",
        drive="volume",
        root_item=str(root.resolve()),
        proposal=proposal,
        year=2025,
    )
    assert sync_scope(scope, LocalSourceAdapter(root)).state == "completed"
    inventory = tmp_path / "file_inventory.jsonl"
    scanner_record = scan_source_root(
        source_root, tmp_path / "scanner-output", dry_run=True
    ).inventory_records[0]
    inventory.write_text(
        json.dumps(scanner_record.model_dump(mode="json")) + "\n",
        encoding="utf-8",
    )
    report, _ = legacy_import.prepare_legacy_import(user, collection.id, inventory=inventory)
    assert report["inventory"]["accepted"] == 1
    path.rename(root / "renamed.txt")
    assert sync_scope(scope, LocalSourceAdapter(root)).state == "completed"
    report, _ = legacy_import.prepare_legacy_import(user, collection.id, inventory=inventory)
    assert report["inventory"]["accepted"] == 1


def test_repeated_same_bytes_on_one_source_reuses_latest_observation(owner, tmp_path):
    user, collection = owner
    _capture(user, collection, "A.txt", b"same", "a")
    latest = services.observe_source(
        user,
        collection.id,
        identity={
            "collection_id": collection.id,
            "connector": "local",
            "tenant": "local",
            "site": "fixture",
            "drive": "2025",
            "item": "a",
        },
        path="C:/archive/2025/Proposal A/A.txt",
        observation_key="v2",
        content=b"same",
        proposal="legacy-proposal",
        family="Proposal A",
    )
    inventory = tmp_path / "file_inventory.jsonl"
    inventory.write_text(json.dumps(_inventory("A.txt", b"same")) + "\n", encoding="utf-8")
    report, _ = legacy_import.prepare_legacy_import(user, collection.id, inventory=inventory)
    assert report["identity_map"]["doc_old"]["source_version_id"] == str(latest.id)


def test_import_preserves_original_and_is_idempotent(owner, tmp_path):
    user, collection = owner
    _capture(user, collection, "A.txt", b"one", "a")
    path = tmp_path / "file_inventory.jsonl"
    original = json.dumps(_inventory("A.txt", b"one"), sort_keys=True).encode() + b"\n"
    path.write_bytes(original)
    first, created = legacy_import.commit_legacy_import(user, collection.id, inventory=path)
    again, created_again = legacy_import.commit_legacy_import(user, collection.id, inventory=path)
    assert created and not created_again and first.id == again.id
    assert m.LegacyImport.objects.count() == 1
    digest = hashlib.sha256(original).hexdigest()
    assert LocalObjectStorage(tmp_path / "objects").get(digest) == original
    assert m.Decision.objects.count() == 0
    assert m.PublicationArtifact.objects.count() == 0


def test_stale_duplicate_and_partial_answers_quarantined(owner, tmp_path):
    user, collection = owner
    _capture(user, collection, "A.txt", b"current", "a")
    path = tmp_path / "file_inventory.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                _inventory("A.txt", b"old", "stale"),
                _inventory("A.txt", b"current", "ambiguous"),
                _inventory("A.txt", b"current", "ambiguous"),
                _inventory("A.txt", b"current", "valid"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    answers = tmp_path / "questions_to_answer.csv"
    answer = {key: "" for key in REVIEW_COLUMNS}
    answer.update(
        question_id="q1",
        document_id="valid",
        proposal_id="legacy-proposal",
        source_path="C:/archive/2025/Proposal A/A.txt",
        scope="document",
        field="include_in_future_rag",
        user_answer="true",
        evidence_summary="Only the methods passage was approved.",
    )
    answers.write_bytes(_csv_bytes(REVIEW_COLUMNS, [answer]))
    report, _ = legacy_import.prepare_legacy_import(
        user, collection.id, inventory=path, answers=answers
    )
    assert report["inventory"] == {"accepted": 1, "quarantined": 3}
    assert report["quarantine"]["inventory"]["stale"] == "source_unresolved"
    assert report["quarantine"]["inventory"]["ambiguous"] == "duplicate_legacy_id"
    assert report["quarantine"]["answers"]["q1"] == "inclusion_requires_current_review"


def test_invalid_metadata_and_unverified_answer_quarantined(owner, tmp_path):
    user, collection = owner
    _capture(user, collection, "A.txt", b"one", "a")
    inventory = tmp_path / "file_inventory.jsonl"
    inventory.write_text(json.dumps(_inventory("A.txt", b"one")) + "\n", encoding="utf-8")
    metadata = tmp_path / "all_document_metadata.jsonl"
    metadata.write_text(json.dumps({"document_id": "doc_old"}) + "\n", encoding="utf-8")
    answers = tmp_path / "questions_to_answer.csv"
    answer = {key: "" for key in REVIEW_COLUMNS}
    answer.update(
        question_id="q1",
        document_id="doc_old",
        proposal_id="legacy-proposal",
        source_path="C:/archive/2025/Proposal A/A.txt",
        scope="document",
        field="agency",
        user_answer="DOE",
    )
    answers.write_bytes(_csv_bytes(REVIEW_COLUMNS, [answer]))
    report, _ = legacy_import.prepare_legacy_import(
        user, collection.id, inventory=inventory, metadata=metadata, answers=answers
    )
    assert report["quarantine"]["metadata"]["doc_old"] == "invalid_metadata_schema"
    assert report["quarantine"]["answers"]["q1"] == "answer_evidence_unverified"


def test_valid_metadata_and_answer_are_accepted_as_lineage(owner, tmp_path):
    user, collection = owner
    _capture(user, collection, "A.txt", b"one", "a")
    record = _inventory("A.txt", b"one")
    inventory = tmp_path / "file_inventory.jsonl"
    inventory.write_text(json.dumps(record) + "\n", encoding="utf-8")
    metadata = tmp_path / "all_document_metadata.jsonl"
    model = analyze_document_mock(InventoryRecord.model_validate(record), "legacy-test")
    metadata.write_text(model.model_dump_json() + "\n", encoding="utf-8")
    answers = tmp_path / "questions_to_answer.csv"
    answer = {key: "" for key in REVIEW_COLUMNS}
    answer.update(
        question_id="q1",
        document_id="doc_old",
        proposal_id="legacy-proposal",
        source_path=record["source_path"],
        scope="document",
        field="agency",
        user_answer="DOE",
        evidence_summary="Administrative cover sheet",
    )
    answers.write_bytes(_csv_bytes(REVIEW_COLUMNS, [answer]))
    report, _ = legacy_import.prepare_legacy_import(
        user, collection.id, inventory=inventory, metadata=metadata, answers=answers
    )
    assert report["metadata"]["accepted"] == 1
    assert report["answers"]["accepted"] == 1
    assert not report["quarantine"]["metadata"]
    assert not report["quarantine"]["answers"]


def test_metadata_unhashable_document_id_is_quarantined(owner, tmp_path):
    user, collection = owner
    _capture(user, collection, "A.txt", b"one", "a")
    inventory = tmp_path / "file_inventory.jsonl"
    inventory.write_text(json.dumps(_inventory("A.txt", b"one")) + "\n", encoding="utf-8")
    metadata = tmp_path / "all_document_metadata.jsonl"
    metadata.write_text(json.dumps({"document_id": ["x"]}) + "\n", encoding="utf-8")
    report, _ = legacy_import.prepare_legacy_import(
        user, collection.id, inventory=inventory, metadata=metadata
    )
    assert report["quarantine"]["metadata"]["row:1"] == "invalid_metadata_schema"


def test_old_version_answer_requires_new_review(owner, tmp_path):
    user, collection = owner
    first = _capture(user, collection, "A.txt", b"old", "a")
    services.observe_source(
        user,
        collection.id,
        identity={
            "collection_id": collection.id,
            "connector": "local",
            "tenant": "local",
            "site": "fixture",
            "drive": "2025",
            "item": "a",
        },
        path="C:/archive/2025/Proposal A/A.txt",
        observation_key="v2",
        content=b"new",
        proposal="legacy-proposal",
        family="Proposal A",
    )
    inventory = tmp_path / "file_inventory.jsonl"
    inventory.write_text(json.dumps(_inventory("A.txt", b"old")) + "\n", encoding="utf-8")
    answers = tmp_path / "questions_to_answer.csv"
    answer = {key: "" for key in REVIEW_COLUMNS}
    answer.update(
        question_id="q-old",
        document_id="doc_old",
        proposal_id="legacy-proposal",
        source_path="C:/archive/2025/Proposal A/A.txt",
        scope="document",
        field="agency",
        user_answer="DOE",
        evidence_summary="Original administrative line",
    )
    answers.write_bytes(_csv_bytes(REVIEW_COLUMNS, [answer]))
    report, _ = legacy_import.prepare_legacy_import(
        user, collection.id, inventory=inventory, answers=answers
    )
    assert report["identity_map"]["doc_old"]["source_version_id"] == str(first.id)
    assert report["quarantine"]["answers"]["q-old"] == "stale_source_version"


def test_management_command_dry_run_is_nonmutating(owner, tmp_path, settings):
    user, collection = owner
    _capture(user, collection, "A.txt", b"one", "a")
    original_objects = set(settings.LOCAL_STORAGE_ROOT.iterdir())
    inventory = tmp_path / "file_inventory.jsonl"
    inventory.write_text(json.dumps(_inventory("A.txt", b"one")) + "\n", encoding="utf-8")
    output = io.StringIO()
    call_command(
        "import_legacy",
        collection=str(collection.id),
        user=user.username,
        inventory=str(inventory),
        stdout=output,
    )
    assert json.loads(output.getvalue())["inventory"] == {"accepted": 1, "quarantined": 0}
    assert not m.LegacyImport.objects.exists()
    assert set(settings.LOCAL_STORAGE_ROOT.iterdir()) == original_objects


def test_management_command_rejects_malformed_collection_uuid(owner, tmp_path):
    user, _ = owner
    inventory = tmp_path / "file_inventory.jsonl"
    inventory.write_text("", encoding="utf-8")
    with pytest.raises(CommandError):
        call_command(
            "import_legacy",
            collection="not-a-uuid",
            user=user.username,
            inventory=str(inventory),
        )


def test_truncated_answer_row_is_quarantined_in_dry_run(owner, tmp_path):
    user, collection = owner
    _capture(user, collection, "A.txt", b"one", "a")
    inventory = tmp_path / "file_inventory.jsonl"
    inventory.write_text(json.dumps(_inventory("A.txt", b"one")) + "\n", encoding="utf-8")
    answers = tmp_path / "questions_to_answer.csv"
    answers.write_text(
        ",".join(REVIEW_COLUMNS) + "\n" + "q-truncated,legacy-proposal\n",
        encoding="utf-8",
    )
    report, _ = legacy_import.prepare_legacy_import(
        user, collection.id, inventory=inventory, answers=answers
    )
    assert report["quarantine"]["answers"]["q-truncated"] == "invalid_answer_row"
