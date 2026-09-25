"""MVP-06 fictional publication, reconciliation, and eligibility boundaries."""

import copy
import hashlib
import io
import runpy
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import timedelta
from threading import Event

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import Client
from django.utils import timezone

from proposal_app import (
    curation,
    extraction_service,
    jobs,
    models as m,
    publication,
    services,
    workflow,
)
from proposal_app.adapters import DeterministicDraftingAdapter
from proposal_app.storage import LocalObjectStorage

pytestmark = pytest.mark.django_db


def test_publication_hold_uses_yaml_default_until_environment_overrides(settings, monkeypatch):
    from proposal_ingest import config

    defaults = copy.deepcopy(config.load_web_application_defaults())
    defaults["publication_hold"] = True
    monkeypatch.setattr(config, "load_web_application_defaults", lambda: defaults.copy())
    monkeypatch.delenv("PROPOSAL_PUBLICATION_HOLD", raising=False)
    settings_path = settings.ROOT / "src" / "proposal_app" / "settings.py"
    assert runpy.run_path(str(settings_path))["APP"]["publication_hold"] is True
    monkeypatch.setenv("PROPOSAL_PUBLICATION_HOLD", "false")
    assert runpy.run_path(str(settings_path))["APP"]["publication_hold"] is False


@pytest.fixture
def corpus(settings, tmp_path):
    settings.LOCAL_STORAGE_ROOT = tmp_path / "objects"
    settings.APP = copy.deepcopy(settings.APP)
    user = get_user_model().objects.create_user(username="mvp06-owner")
    m.Identity.objects.create(user=user, issuer="local", subject="mvp06-owner", allowed=True)
    collection = m.Collection.objects.create(name="Fictional publication")
    m.CollectionAccess.objects.create(user=user, collection=collection)

    def capture(text, *, item="source", observation="v1", proposal="FICTIONAL-06"):
        version = services.observe_source(
            user,
            collection.id,
            identity={
                "connector": "local",
                "tenant": "test",
                "site": "test",
                "drive": "test",
                "item": item,
            },
            path=f"2025/Fictional-06/{item}.txt",
            observation_key=observation,
            content=text.encode(),
            proposal=proposal,
            family="source",
        )
        run = extraction_service.extract_version(user, version.id)
        for _ in range(40):
            if not m.Job.objects.filter(kind="classify-unit", state="queued").exists():
                break
            assert jobs.work_once()
        family = m.VersionFamily.objects.get(
            proposal__collection=collection, proposal__identifier=proposal, key="source"
        )
        return version, run, family

    return user, collection, capture


class FakeKB:
    def __init__(self):
        self.objects = {}
        self.index = {}
        self.upload_failure = False
        self.job_state = "IN_PROGRESS"
        self.calls = 0
        self.results = []

    def uri(self, artifact):
        return f"s3://private-fixture/{artifact.object_key}"

    def verify_scope(self):
        return None

    def upload(self, artifact, raw):
        if self.upload_failure:
            raise RuntimeError("synthetic upload failure")
        self.objects[self.uri(artifact)] = raw
        self.objects[self.uri(artifact) + ".metadata.json"] = publication._json_bytes(
            artifact.metadata
        )

    def start(self, generation, *, operation="publish"):
        self.calls += 1
        return f"job-{self.calls}"

    def job(self, job_id):
        return {"status": self.job_state}

    def statuses(self, artifacts):
        return {self.uri(item): self.index.get(self.uri(item), "NOT_FOUND") for item in artifacts}

    def retrieve(self, query):
        return self.results

    def delete(self, artifact):
        self.objects.pop(self.uri(artifact), None)
        self.objects.pop(self.uri(artifact) + ".metadata.json", None)


def _plan(corpus, text="Technical fictional binder stability is supported."):
    _, _, capture = corpus
    version, run, family = capture(text)
    plan = m.CurationPlan.objects.get(family=family, version=version, state="current")
    assert plan.eligible_units
    return version, run, family, plan


def test_auto_plan_uploads_only_curated_bytes_and_rejects_unmapped_results(corpus, settings):
    user, collection, _ = corpus
    version, _, family, plan = _plan(
        corpus,
        "Technical fictional binder stability is supported.\n\n"
        "[sensitive] Personal information about a fictional participant.",
    )
    assert len(plan.eligible_units) == 1 and len(plan.excluded_units) == 1
    settings.APP["publication_backend"] = "managed_kb"
    generation = publication.stage(user, family.proposal_id)
    artifact = m.PublicationArtifact.objects.get(generation=generation)
    assert artifact.source_unit_ids == plan.eligible_units
    assert artifact.unit.version_id == version.id
    assert artifact.locator == artifact.unit.locator
    assert artifact.decision_event.revision == artifact.decision_event.decision.revision
    fake = FakeKB()
    assert publication.process(generation.id, fake).state == "indexing"
    assert b"binder stability" in fake.objects[fake.uri(artifact)]
    assert b"Personal information" not in b"".join(fake.objects.values())
    assert publication.process(generation.id, fake).state == "indexing"
    fake.job_state = "COMPLETE"
    fake.index[fake.uri(artifact)] = "INDEXED"
    assert publication.process(generation.id, fake).state == "active"
    metadata = artifact.metadata["metadataAttributes"]
    fake.results = [
        {
            "metadata": metadata,
            "location": {"s3Location": {"uri": fake.uri(artifact)}},
            "content": {"text": "untrusted provider replacement"},
            "score": 0.9,
        },
        {"metadata": {"artifact_id": "unknown"}, "content": {"text": "forbidden"}},
    ]
    result = publication.retrieve(user, collection.id, "binder", fake)
    assert len(result) == 1
    assert "binder stability" in result[0]["text"]
    assert "untrusted provider" not in str(result)
    assert publication.validate_packet(user, collection.id, result)
    fake.results = [
        {
            "metadata": metadata,
            "location": {"s3Location": {"uri": fake.uri(artifact)}},
            "score": score,
        }
        for score in (0.2, 0.95, 0.5)
    ] + [{"metadata": {"artifact_id": {}}, "location": None}]
    deduplicated = publication.retrieve(user, collection.id, "binder", fake)
    assert len(deduplicated) == 1 and deduplicated[0]["score"] == 0.95
    session = services.create_draft(user, collection.id, "Fictional writing")
    workflow.pin_evidence(user, session.id, artifact.id)
    draft = workflow.generate(user, session.id, "Describe the binder")
    assert "Personal information" not in str(draft.packet.payload)
    decision = m.Decision.objects.get(
        family=family, scope=f"unit:{artifact.unit_id}", field="treatment"
    )
    curation.review(
        user,
        decision.id,
        decision.revision,
        "edit",
        value={"treatment": "excluded"},
        rationale="Reviewer correction after publication.",
    )
    curation.build_plan(user, family.id, version.id)
    assert publication.retrieve(user, collection.id, "binder", fake) == []
    assert not publication.validate_packet(user, collection.id, result)
    with pytest.raises(ValueError, match="currently eligible"):
        workflow.generate(user, session.id, "Try stale pin")


def test_regeneration_rejects_stale_prior_packet_with_other_valid_pin(corpus):
    user, collection, _ = corpus
    version, _, family, plan = _plan(
        corpus,
        "Technical fictional binder stability is supported.\n\n"
        "Technical fictional cell capacity is supported.",
    )
    assert len(plan.eligible_units) == 2
    generation = publication.stage(user, family.proposal_id)
    assert publication.process(generation.id).state == "active"
    artifacts = list(m.PublicationArtifact.objects.filter(generation=generation).order_by("id"))
    assert len(artifacts) == 2
    session = services.create_draft(user, collection.id, "Fictional writing")
    for artifact in artifacts:
        workflow.pin_evidence(user, session.id, artifact.id)
    first = workflow.generate(user, session.id, "Describe the evidence")
    assert len(first.packet.payload) == 2

    withdrawn = artifacts[0]
    decision = m.Decision.objects.get(
        family=family, scope=f"unit:{withdrawn.unit_id}", field="treatment"
    )
    curation.review(
        user,
        decision.id,
        decision.revision,
        "edit",
        value={"treatment": "excluded"},
        rationale="Fictional reviewer correction.",
    )
    curation.build_plan(user, family.id, version.id)
    assert (
        len(services.factual_artifacts(user, collection.id, [item.id for item in artifacts])) == 1
    )
    with pytest.raises(ValueError, match="Previous evidence changed"):
        workflow.generate(user, session.id, "Regenerate with remaining pin")
    refreshed = workflow.generate(
        user, session.id, "Use only current evidence", refresh_evidence=True
    )
    assert len(refreshed.packet.payload) == 1
    assert str(withdrawn.id) not in str(refreshed.packet.payload)
    assert withdrawn.unit.text not in refreshed.text
    assert m.DraftRevision.objects.filter(session=session).count() == 2
    legacy_payload = copy.deepcopy(refreshed.packet.payload)
    legacy_payload[0].pop("generation_id")
    legacy_packet = m.EvidencePacket.objects.create(
        session=session, payload=legacy_payload, policy_revision="legacy-fixture-v1"
    )
    session.refresh_from_db()
    session.revision += 1
    session.save(update_fields=["revision"])
    m.DraftRevision.objects.create(
        session=session,
        number=session.revision,
        packet=legacy_packet,
        text="Historical fictional draft text.",
    )
    with pytest.raises(ValueError, match="refresh from current pins"):
        workflow.generate(user, session.id, "Legacy packet")
    recovered = workflow.generate(user, session.id, "Current pins only", refresh_evidence=True)
    assert len(recovered.packet.payload) == 1
    assert m.DraftRevision.objects.filter(session=session).count() == 4


def test_failure_retry_partial_index_and_replacement_keep_old_generation(corpus, settings):
    user, collection, capture = corpus
    old, _, family, _ = _plan(corpus)
    settings.APP["publication_backend"] = "managed_kb"
    fake = FakeKB()
    first = publication.stage(user, family.proposal_id)
    artifact = m.PublicationArtifact.objects.get(generation=first)
    publication.process(first.id, fake)
    fake.job_state = "COMPLETE"
    fake.index[fake.uri(artifact)] = "INDEXED"
    publication.process(first.id, fake)
    first.refresh_from_db()
    assert first.state == "active"
    new, _, _ = capture("Technical fictional binder stability improved.", observation="v2")
    assert new.id != old.id
    second = publication.stage(user, family.proposal_id)
    assert second.id != first.id
    fake.upload_failure = True
    assert publication.process(second.id, fake).failure == "upload_failed"
    assert m.PublicationGeneration.objects.get(pk=first.id).state == "active"
    browser = Client()
    browser.force_login(user)
    status_page = browser.get(f"/collections/{collection.id}/")
    assert status_page.status_code == 200
    assert b"latest publication failed (upload_failed)" in status_page.content
    assert b"last successful generation 1" in status_page.content
    fake.upload_failure = False
    fake.job_state = "IN_PROGRESS"
    assert publication.process(second.id, fake).state == "indexing"
    second_artifact = m.PublicationArtifact.objects.get(generation=second)
    fake.job_state = "COMPLETE"
    fake.index[fake.uri(second_artifact)] = "PARTIALLY_INDEXED"
    assert publication.process(second.id, fake).failure == "documents_not_indexed"
    assert m.PublicationGeneration.objects.get(pk=first.id).state == "active"
    fake.index[fake.uri(second_artifact)] = "INDEXED"
    assert publication.process(second.id, fake).state == "active"
    first.refresh_from_db()
    assert first.state == "retired"
    fake.results = [
        {
            "metadata": artifact.metadata["metadataAttributes"],
            "location": {"s3Location": {"uri": fake.uri(artifact)}},
        },
        {
            "metadata": second_artifact.metadata["metadataAttributes"],
            "location": {"s3Location": {"uri": fake.uri(second_artifact)}},
        },
    ]
    found = publication.retrieve(user, collection.id, "binder", fake)
    assert [item["artifact_id"] for item in found] == [str(second_artifact.id)]
    assert publication.process(second.id, fake).id == second.id
    assert fake.calls == 3


def test_uncertain_ingestion_start_reuses_remote_job(corpus, settings):
    user, _, _ = corpus
    _, _, family, _ = _plan(corpus)
    settings.APP["publication_backend"] = "managed_kb"
    generation = publication.stage(user, family.proposal_id)
    artifact = m.PublicationArtifact.objects.get(generation=generation)

    class UncertainStart(FakeKB):
        def __init__(self):
            super().__init__()
            self.accepted = {}
            self.lost_response = False

        def start(self, generation, *, operation="publish"):
            token_identity = (generation.id, operation, generation.ingestion_job_id)
            job_id = self.accepted.setdefault(token_identity, "accepted-once")
            if not self.lost_response:
                self.lost_response = True
                raise TimeoutError("Response lost after remote acceptance")
            return job_id

    fake = UncertainStart()
    assert publication.process(generation.id, fake).failure == "ingestion_start_failed"
    assert len(fake.accepted) == 1
    assert publication.process(generation.id, fake).state == "indexing"
    generation.refresh_from_db()
    assert generation.ingestion_job_id == "accepted-once"
    assert len(fake.accepted) == 1
    fake.job_state = "COMPLETE"
    fake.index[fake.uri(artifact)] = "INDEXED"
    assert publication.process(generation.id, fake).state == "active"


def test_conflict_defers_start_and_late_retry_gets_new_deadline(corpus, settings):
    user, _, _ = corpus
    _, _, family, _ = _plan(corpus)
    settings.APP["publication_backend"] = "managed_kb"
    settings.APP["publication_reconcile_timeout_seconds"] = 1
    generation = publication.stage(user, family.proposal_id)
    artifact = m.PublicationArtifact.objects.get(generation=generation)

    class Conflict(Exception):
        response = {"Error": {"Code": "ConflictException"}}

    class ContendedKB(FakeKB):
        def start(self, generation, *, operation="publish"):
            if not self.calls:
                self.calls += 1
                raise Conflict("Fictional concurrent ingestion")
            return super().start(generation, operation=operation)

    fake = ContendedKB()
    result = publication.process(generation.id, fake)
    assert (result.state, result.failure, result.ingestion_job_id) == (
        "uploaded",
        "ingestion_start_deferred",
        "",
    )
    m.PublicationGeneration.objects.filter(pk=generation.id).update(
        created_at=timezone.now() - timedelta(minutes=5)
    )
    result = publication.process(generation.id, fake)
    assert result.state == "indexing"
    assert result.indexing_started_at > result.created_at
    fake.job_state = "COMPLETE"
    fake.index[fake.uri(artifact)] = "INDEXED"
    assert publication.process(generation.id, fake).state == "active"


def test_observation_failures_time_out_and_missing_adapter_fails(corpus, settings, monkeypatch):
    user, _, _ = corpus
    _, _, family, _ = _plan(corpus)
    settings.APP["publication_backend"] = "managed_kb"
    settings.APP["publication_reconcile_timeout_seconds"] = 1

    class UnobservableJob(FakeKB):
        def job(self, job_id):
            raise OSError("Fictional service outage")

    generation = publication.stage(user, family.proposal_id)
    fake = UnobservableJob()
    assert publication.process(generation.id, fake).failure == "ingestion_observation_failed"
    m.PublicationGeneration.objects.filter(pk=generation.id).update(
        indexing_started_at=timezone.now() - timedelta(seconds=2)
    )
    result = publication.process(generation.id, fake)
    assert (result.state, result.failure) == ("failed", "ingestion_observation_timeout")

    class UnobservableDocuments(FakeKB):
        def statuses(self, artifacts):
            raise OSError("Fictional document lookup outage")

    next_generation = publication.stage(user, family.proposal_id)
    fake = UnobservableDocuments()
    fake.job_state = "COMPLETE"
    assert publication.process(next_generation.id, fake).failure == "document_observation_failed"
    m.PublicationGeneration.objects.filter(pk=next_generation.id).update(
        indexing_started_at=timezone.now() - timedelta(seconds=2)
    )
    result = publication.process(next_generation.id, fake)
    assert (result.state, result.failure) == ("failed", "document_observation_timeout")

    def unavailable():
        raise ValueError("Fictional missing configuration")

    monkeypatch.setattr(publication, "ManagedKBAdapter", unavailable)
    final_generation = publication.stage(user, family.proposal_id)
    result = publication.process(final_generation.id)
    assert (result.state, result.failure) == ("failed", "adapter_unavailable")


def test_source_exclusion_during_draft_and_deletion_lag(corpus, settings, monkeypatch):
    user, collection, _ = corpus
    version, _, family, _ = _plan(corpus)
    settings.APP["publication_backend"] = "managed_kb"
    fake = FakeKB()
    generation = publication.stage(user, family.proposal_id)
    artifact = m.PublicationArtifact.objects.get(generation=generation)
    publication.process(generation.id, fake)
    fake.job_state = "COMPLETE"
    fake.index[fake.uri(artifact)] = "INDEXED"
    publication.process(generation.id, fake)
    session = services.create_draft(user, collection.id, "Fictional draft")
    workflow.pin_evidence(user, session.id, artifact.id)
    original = DeterministicDraftingAdapter.draft

    def exclude_during_call(self, packet, prompt, *, idempotency_key):
        version.source.disposition = "excluded"
        version.source.save(update_fields=["disposition"])
        return original(self, packet, prompt, idempotency_key=idempotency_key)

    monkeypatch.setattr(DeterministicDraftingAdapter, "draft", exclude_during_call)
    with pytest.raises(ValueError, match="changed during drafting"):
        workflow.generate(user, session.id, "Use evidence")
    assert not m.DraftRevision.objects.filter(session=session).exists()
    generation.state = "retired"
    generation.save(update_fields=["state"])
    assert publication.cleanup_retired(generation.id, fake).deletion_state == "pending"
    assert publication.retrieve(user, collection.id, "binder", fake) == []
    fake.index[fake.uri(artifact)] = "NOT_FOUND"
    assert publication.cleanup_retired(generation.id, fake).deletion_state == "complete"
    assert fake.uri(artifact) not in fake.objects


def test_full_partial_summary_metadata_only_and_excluded_render_exact_bytes(corpus, settings):
    user, collection, _ = corpus
    version, run, family, _ = _plan(
        corpus,
        "Technical fictional full passage alpha.\n\n"
        "Technical fictional raw passage beta.\n\n"
        "Technical fictional metadata passage gamma.\n\n"
        "Technical fictional excluded passage delta.",
    )
    units = list(m.ExtractedUnit.objects.filter(extraction_run=run).order_by("ordinal"))
    assert len(units) == 4
    treatments = [
        {"treatment": "partial", "selected_units": [str(units[0].id)]},
        {
            "treatment": "summary",
            "source_units": [str(units[1].id)],
            "summary": "Derived fictional approved summary.",
            "voice_eligible": False,
        },
        {"treatment": "metadata_only"},
        {"treatment": "excluded"},
    ]
    for unit, value in zip(units, treatments):
        decision = m.Decision.objects.get(family=family, scope=f"unit:{unit.id}", field="treatment")
        curation.review(
            user,
            decision.id,
            decision.revision,
            "edit",
            value=value,
            rationale="Fictional source-checked treatment.",
        )
    plan = curation.build_plan(user, family.id, version.id)
    assert len(plan.eligible_units) == 1
    assert len(plan.derived_summaries) == 1
    assert len(plan.metadata_only_units) == 1
    assert len(plan.excluded_units) == 2
    generation = publication.stage(user, family.proposal_id)
    assert publication.process(generation.id).state == "active"
    artifacts = list(
        m.PublicationArtifact.objects.filter(generation=generation).select_related("blob")
    )
    assert {artifact.kind for artifact in artifacts} == {"excerpt", "summary"}
    raw = b"\n".join(
        LocalObjectStorage(settings.LOCAL_STORAGE_ROOT).get(artifact.blob.storage_key)
        for artifact in artifacts
    )
    assert b"full passage alpha" in raw
    assert b"Derived fictional approved summary" in raw
    assert b"raw passage beta" not in raw
    assert b"metadata passage gamma" not in raw
    assert b"excluded passage delta" not in raw
    summary = next(artifact for artifact in artifacts if artifact.kind == "summary")
    assert summary.source_unit_ids == [str(units[1].id)]
    assert workflow.search(user, collection.id, "raw beta") == []
    assert workflow.search(user, collection.id, "Derived fictional approved summary")
    session = services.create_draft(user, collection.id, "Summary packet")
    workflow.pin_evidence(user, session.id, summary.id)
    browser = Client()
    browser.force_login(user)
    writing_page = browser.get(f"/writing/{session.id}/")
    assert b"Derived fictional approved summary" in writing_page.content
    assert b"raw passage beta" not in writing_page.content
    draft = workflow.generate(user, session.id, "Use summary")
    assert "Derived fictional approved summary" in str(draft.packet.payload)
    assert "raw passage beta" not in str(draft.packet.payload)


def test_summary_withdraws_when_non_anchor_source_is_excluded(corpus):
    user, collection, _ = corpus
    version, run, family, _ = _plan(
        corpus,
        "Technical fictional binder result alpha.\n\n" "Technical fictional binder result beta.",
    )
    units = list(m.ExtractedUnit.objects.filter(extraction_run=run).order_by("ordinal"))
    source_ids = [str(unit.id) for unit in units]
    decision = curation.recommend(
        user,
        family.id,
        f"version:{version.id}",
        "treatment",
        "curation",
        value={
            "treatment": "summary",
            "source_units": source_ids,
            "summary": "Approved fictional combined result.",
            "voice_eligible": False,
        },
        rationale="Fictional source-backed summary.",
        evidence=source_ids,
        affected_units=source_ids,
    )
    curation.review(user, decision.id, decision.revision, "approve")
    plan = curation.build_plan(user, family.id, version.id)
    assert len(plan.derived_summaries) == 1
    generation = publication.stage(user, family.proposal_id)
    assert publication.process(generation.id).state == "active"
    artifact = m.PublicationArtifact.objects.get(generation=generation)
    assert artifact.source_unit_ids == source_ids
    assert workflow.search(user, collection.id, "combined result")

    non_anchor = next(unit for unit in units if unit.id != artifact.unit_id)
    override = m.Decision.objects.get(
        family=family, scope=f"unit:{non_anchor.id}", field="treatment"
    )
    curation.review(
        user,
        override.id,
        override.revision,
        "edit",
        value={"treatment": "excluded"},
        rationale="Fictional reviewer withdrew a supporting unit.",
    )
    assert workflow.search(user, collection.id, "combined result") == []
    plan = curation.build_plan(user, family.id, version.id)
    assert plan.derived_summaries == []
    assert not services.factual_artifacts(user, collection.id, [artifact.id]).exists()


def test_managed_kb_request_contract_and_metadata_limit(corpus, settings, monkeypatch):
    user, _, _ = corpus
    _, _, family, _ = _plan(corpus)
    settings.APP["publication_backend"] = "managed_kb"
    generation = publication.stage(user, family.proposal_id)
    artifact = m.PublicationArtifact.objects.get(generation=generation)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("PROPOSAL_CURATED_BUCKET", "private-fixture")
    monkeypatch.setenv("BEDROCK_KNOWLEDGE_BASE_ID", "KB12345678")
    monkeypatch.setenv("BEDROCK_DATA_SOURCE_ID", "DS12345678")

    class Client:
        def __init__(self):
            self.calls = []

        def put_object(self, **kwargs):
            self.calls.append(("put", kwargs))

        def get_data_source(self, **kwargs):
            self.calls.append(("source", kwargs))
            return {
                "dataSource": {
                    "status": "AVAILABLE",
                    "dataSourceConfiguration": {
                        "type": "S3",
                        "s3Configuration": {
                            "bucketArn": "arn:aws:s3:::private-fixture",
                            "inclusionPrefixes": [settings.APP["publication_s3_prefix"]],
                        },
                    },
                }
            }

        def start_ingestion_job(self, **kwargs):
            self.calls.append(("start", kwargs))
            return {"ingestionJob": {"ingestionJobId": "JOB1234567"}}

        def get_ingestion_job(self, **kwargs):
            self.calls.append(("job", kwargs))
            return {"ingestionJob": {"status": "COMPLETE"}}

        def get_knowledge_base_documents(self, **kwargs):
            self.calls.append(("documents", kwargs))
            return {
                "documentDetails": [
                    {
                        "identifier": kwargs["documentIdentifiers"][0],
                        "status": "INDEXED",
                    }
                ]
            }

        def retrieve(self, **kwargs):
            self.calls.append(("retrieve", kwargs))
            return {"retrievalResults": []}

        def delete_object(self, **kwargs):
            self.calls.append(("delete", kwargs))

    s3, control, runtime = Client(), Client(), Client()
    adapter = publication.ManagedKBAdapter(s3=s3, control=control, runtime=runtime)
    adapter.verify_scope()
    original_source = control.get_data_source

    def unsafe_source(**kwargs):
        result = original_source(**kwargs)
        result["dataSource"]["dataSourceConfiguration"]["s3Configuration"]["inclusionPrefixes"] = [
            ""
        ]
        return result

    control.get_data_source = unsafe_source
    with pytest.raises(ValueError, match="curated bucket prefix"):
        adapter.verify_scope()
    control.get_data_source = original_source
    raw = LocalObjectStorage(settings.LOCAL_STORAGE_ROOT).get(artifact.blob.storage_key)
    adapter.upload(artifact, raw)
    assert len(s3.calls) == 2
    assert all(call[1]["ServerSideEncryption"] == "AES256" for call in s3.calls)
    assert s3.calls[0][1]["Key"] == artifact.object_key
    assert s3.calls[1][1]["Key"] == artifact.object_key + ".metadata.json"
    assert b"Technical fictional" not in s3.calls[1][1]["Body"]
    assert adapter.start(generation) == "JOB1234567"
    assert len(control.calls[-1][1]["clientToken"]) == 64
    assert adapter.job("JOB1234567")["status"] == "COMPLETE"
    assert adapter.statuses([artifact])[adapter.uri(artifact)] == "INDEXED"
    assert adapter.retrieve("binder") == []
    assert runtime.calls[-1][1]["retrievalConfiguration"] == {
        "managedSearchConfiguration": {
            "numberOfResults": settings.APP["publication_retrieve_limit"]
        }
    }
    adapter.delete(artifact)
    assert len([call for call in s3.calls if call[0] == "delete"]) == 2
    settings.APP["publication_max_metadata_bytes"] = 50
    with pytest.raises(ValueError, match="sidecar limit"):
        publication.metadata_for(artifact)


def test_live_mode_requires_current_human_inclusion(corpus, settings):
    user, _, _ = corpus
    version, _, family, _ = _plan(corpus)
    settings.MODE = "production"
    with pytest.raises(ValueError, match="explicit inclusion"):
        publication._plan_specs(family.proposal)
    decision = m.Decision.objects.create(
        family=family,
        scope=f"version:{version.id}",
        field="publication",
        kind="inclusion",
        revision=1,
        status="resolved",
    )
    m.DecisionEvent.objects.create(
        decision=decision,
        revision=1,
        actor=user,
        action="approve",
        value={"treatment": "include", "source_version_id": str(version.id)},
        rationale="Fictional owner inclusion.",
        evidence=[],
        resolver_revision="human-test-v1",
    )
    version.source.disposition = "included"
    version.source.save(update_fields=["disposition"])
    assert publication._plan_specs(family.proposal)[1]


def test_ingestion_timeout_and_unknown_result_after_restore(corpus, settings):
    user, collection, _ = corpus
    _, _, family, _ = _plan(corpus)
    settings.APP["publication_backend"] = "managed_kb"
    settings.APP["publication_reconcile_timeout_seconds"] = 1
    generation = publication.stage(user, family.proposal_id)
    fake = FakeKB()
    assert publication.process(generation.id, fake).state == "indexing"
    m.PublicationGeneration.objects.filter(pk=generation.id).update(
        indexing_started_at=timezone.now() - timedelta(seconds=2)
    )
    assert publication.process(generation.id, fake).failure == "ingestion_timeout"
    fake.results = [
        {
            "metadata": {
                "artifact_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "generation_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            },
            "location": {"s3Location": {"uri": "s3://private-fixture/unknown.txt"}},
            "content": {"text": "newer index content absent from restored application state"},
        }
    ]
    assert publication.retrieve(user, collection.id, "unknown", fake) == []


def test_recovery_hold_and_verified_rollback_obey_latest_decisions(corpus, settings):
    user, collection, _ = corpus
    version, _, family, _ = _plan(corpus)
    generation = publication.stage(user, family.proposal_id)
    publication.process(generation.id)
    artifact = m.PublicationArtifact.objects.get(generation=generation)
    session = services.create_draft(user, collection.id, "Recovery draft")
    workflow.pin_evidence(user, session.id, artifact.id)
    settings.APP["publication_hold"] = True
    assert workflow.search(user, collection.id, "binder") == []
    with pytest.raises(ValueError, match="currently eligible"):
        workflow.generate(user, session.id, "Blocked during restore")
    with pytest.raises(ValueError, match="held"):
        publication.stage(user, family.proposal_id)
    settings.APP["publication_hold"] = False
    generation.state = "retired"
    generation.save(update_fields=["state"])
    assert publication.restore_verified(generation.id).state == "active"
    generation.state = "retired"
    generation.save(update_fields=["state"])
    decision = m.Decision.objects.get(
        family=family, scope=f"unit:{artifact.unit_id}", field="treatment"
    )
    curation.review(
        user,
        decision.id,
        decision.revision,
        "edit",
        value={"treatment": "excluded"},
        rationale="Reviewer withdrew the fictional evidence.",
    )
    curation.build_plan(user, family.id, version.id)
    with pytest.raises(ValueError, match="no longer matches"):
        publication.restore_verified(generation.id)


def test_hold_defers_activation_and_worker_isolates_failed_generation(
    corpus, settings, monkeypatch
):
    user, _, capture = corpus
    _, _, family, _ = _plan(corpus)
    first = publication.stage(user, family.proposal_id)
    _, _, other_family = capture(
        "Technical fictional separator result.", item="other", proposal="OTHER-06"
    )
    second = publication.stage(user, other_family.proposal_id)

    settings.APP["publication_hold"] = True
    assert publication.process(first.id).state == "verified"
    assert publication.reconcile_once() is False
    assert m.PublicationGeneration.objects.get(pk=second.id).state == "staged"
    settings.APP["publication_hold"] = False

    original = publication.process

    def fail_one(generation_id, adapter=None):
        if generation_id == first.id:
            raise OSError("Fictional missing staged bytes")
        return original(generation_id, adapter)

    monkeypatch.setattr(publication, "process", fail_one)
    assert publication.reconcile_once() is True
    failed = m.PublicationGeneration.objects.get(pk=first.id)
    assert (failed.state, failed.failure) == ("failed", "reconcile_error")
    assert m.PublicationGeneration.objects.get(pk=second.id).state == "active"


def test_cleanup_marker_blocks_restore_during_index_deletion_lag(corpus, settings):
    user, _, _ = corpus
    _, _, family, _ = _plan(corpus)
    settings.APP["publication_backend"] = "managed_kb"
    generation = publication.stage(user, family.proposal_id)
    artifact = m.PublicationArtifact.objects.get(generation=generation)
    fake = FakeKB()
    publication.process(generation.id, fake)
    fake.job_state = "COMPLETE"
    fake.index[fake.uri(artifact)] = "INDEXED"
    assert publication.process(generation.id, fake).state == "active"
    generation.state = "retired"
    generation.save(update_fields=["state"])
    assert publication.cleanup_retired(generation.id, fake).deletion_state == "pending"
    assert fake.uri(artifact) not in fake.objects
    retried = publication.cleanup_retired(generation.id, fake)
    assert (retried.deletion_state, retried.deletion_job_id) == ("pending", "job-3")
    with pytest.raises(ValueError, match="cleanup has started"):
        publication.restore_verified(generation.id, fake)


def test_failed_refresh_does_not_interrupt_another_proposal(corpus, settings):
    user, collection, capture = corpus
    _, _, first_family, _ = _plan(corpus)
    _, _, other_family = capture(
        "Technical fictional separator stability is supported.",
        item="other",
        proposal="OTHER-06",
    )
    settings.APP["publication_backend"] = "managed_kb"
    fake = FakeKB()
    fake.job_state = "COMPLETE"
    first = publication.stage(user, first_family.proposal_id)
    other = publication.stage(user, other_family.proposal_id)
    for generation in (first, other):
        publication.process(generation.id, fake)
        artifact = m.PublicationArtifact.objects.get(generation=generation)
        fake.index[fake.uri(artifact)] = "INDEXED"
        assert publication.process(generation.id, fake).state == "active"
    other_artifact = m.PublicationArtifact.objects.get(generation=other)
    capture("Technical fictional changed binder result.", observation="v2")
    replacement = publication.stage(user, first_family.proposal_id)
    fake.upload_failure = True
    assert publication.process(replacement.id, fake).state == "failed"
    assert m.PublicationGeneration.objects.get(pk=other.id).state == "active"
    fake.results = [
        {
            "metadata": other_artifact.metadata["metadataAttributes"],
            "location": {"s3Location": {"uri": fake.uri(other_artifact)}},
        }
    ]
    assert [
        item["artifact_id"] for item in publication.retrieve(user, collection.id, "separator", fake)
    ] == [str(other_artifact.id)]


@pytest.mark.django_db(transaction=True)
def test_activation_serializes_with_plan_invalidation(corpus, monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("Row locking requires PostgreSQL")
    user, collection, _ = corpus
    _, _, family, plan = _plan(corpus)
    generation = publication.stage(user, family.proposal_id)
    m.PublicationArtifact.objects.filter(generation=generation).update(index_state="indexed")
    generation.state = "verified"
    generation.save(update_fields=["state"])
    entered, release = Event(), Event()
    original = publication._still_current

    def pause_during_activation(current):
        entered.set()
        assert release.wait(10)
        return original(current)

    monkeypatch.setattr(publication, "_still_current", pause_during_activation)
    with ThreadPoolExecutor(max_workers=2) as pool:
        activating = pool.submit(publication._activate, generation.id)
        assert entered.wait(10)
        invalidating = pool.submit(
            lambda: m.CurationPlan.objects.filter(pk=plan.id).update(state="invalidated")
        )
        with pytest.raises(FutureTimeout):
            invalidating.result(timeout=0.2)
        release.set()
        assert activating.result(timeout=10).state == "active"
        assert invalidating.result(timeout=10) == 1
    assert not services.factual_artifacts(
        user,
        collection.id,
        m.PublicationArtifact.objects.filter(generation=generation).values_list("id", flat=True),
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_operator_demo_reads_source_without_writing_and_publishes_current_plan(settings, tmp_path):
    if connection.vendor != "postgresql":
        pytest.skip("The source-sync demo uses PostgreSQL advisory locks")
    settings.LOCAL_STORAGE_ROOT = tmp_path / "objects"
    fixture = (
        settings.ROOT / settings.APP["classification_demo_source_root"] / "fictional_source.txt"
    )
    source_before = fixture.read_bytes()
    mtime_before = fixture.stat().st_mtime_ns
    output = io.StringIO()
    call_command("fixture_publication", stdout=output)
    generation = m.PublicationGeneration.objects.get(proposal__identifier="FICTIONAL-05B")
    assert generation.state == "active" and generation.expected_count == 1
    artifact = m.PublicationArtifact.objects.get(generation=generation)
    raw = LocalObjectStorage(settings.LOCAL_STORAGE_ROOT).get(artifact.blob.storage_key)
    assert b"binder" in raw.lower()
    assert b"Personal information" not in raw
    assert fixture.read_bytes() == source_before
    assert hashlib.sha256(fixture.read_bytes()).digest() == hashlib.sha256(source_before).digest()
    assert fixture.stat().st_mtime_ns == mtime_before
    assert "state=active" in output.getvalue()
