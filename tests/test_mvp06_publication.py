"""MVP-06 fictional publication, reconciliation, and eligibility boundaries."""

import copy
import hashlib
import io
from datetime import timedelta

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
    draft = workflow.generate(user, session.id, "Use summary")
    assert "Derived fictional approved summary" in str(draft.packet.payload)
    assert "raw passage beta" not in str(draft.packet.payload)


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
        created_at=timezone.now() - timedelta(seconds=2)
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
