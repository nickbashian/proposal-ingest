"""MVP-05b operational ingestion acceptance over fictional source text."""

import copy
import io
import uuid
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from proposal_app import (
    classification,
    curation,
    extraction_service,
    jobs,
    models as m,
    services,
    source_sync,
    workflow,
)
from proposal_app.adapters import CallResult
from proposal_app.storage import LocalObjectStorage

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(settings, tmp_path):
    settings.LOCAL_STORAGE_ROOT = tmp_path / "snapshots"
    user = get_user_model().objects.create_user(username="mvp05b-owner")
    m.Identity.objects.create(user=user, issuer="local", subject="mvp05b-owner", allowed=True)
    collection = m.Collection.objects.create(name="Fictional ingestion")
    m.CollectionAccess.objects.create(user=user, collection=collection)
    return user, collection


def capture(owner, text, *, item=None, observation=None):
    user, collection = owner
    item = item or str(uuid.uuid4())
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
        path=f"2025/P-05b/{item}.txt",
        observation_key=observation or str(uuid.uuid4()),
        content=text.encode(),
        proposal="P-05b",
        family="source",
    )
    run = extraction_service.extract_version(user, version.id)
    family = m.VersionFamily.objects.get(proposal__collection=collection, key="source")
    return version, run, family


def drain():
    for _ in range(50):
        if not m.Job.objects.filter(
            kind="classify-unit", state__in=["queued", "running", "delivering"]
        ).exists():
            return
        assert jobs.work_once()
    raise AssertionError("Classification did not drain")


def test_source_to_automatic_plan_and_idempotent_rerun(owner):
    version, run, family = capture(owner, "Technical discussion of synthetic binder stability.")
    queued = list(m.Job.objects.filter(kind="classify-unit"))
    assert len(queued) == m.ExtractedUnit.objects.filter(extraction_run=run).count()
    drain()
    plan = m.CurationPlan.objects.get(family=family, version=version, state="current")
    assert len(plan.eligible_units) == 1
    assert plan.pending_units == []
    unit = m.ExtractedUnit.objects.get(pk=plan.eligible_units[0])
    assert unit.support_kind == "unclassified"  # Extraction history is immutable.
    result = m.ClassificationResult.objects.get(unit=unit)
    assert result.state == "succeeded"
    assert set(result.predictions) == curation.DIMENSIONS
    assert result.version_id == version.id and result.extraction_run_id == run.id
    assert result.model_revision and result.prompt_revision and result.schema_revision
    assert m.ClassificationFact.objects.filter(unit=unit, origin="model").count() == 10
    decision = m.Decision.objects.get(family=family, scope=f"unit:{unit.id}", field="treatment")
    assert curation.current_event(decision).action == "automatic"
    assert classification.workload(owner[1].id)[0]["automatic"] == 1
    assert curation.review_queue(owner[1].id)["all"] == []
    extraction_service.extract_version(owner[0], version.id)
    assert m.Job.objects.filter(kind="classify-unit").count() == len(queued)
    assert m.DecisionEvent.objects.filter(decision=decision, action="automatic").count() == 1


def test_exception_queue_human_correction_and_revised_plan(owner, settings):
    version, _, family = capture(
        owner,
        "Technical discussion of synthetic binder stability.\n\n"
        "[sensitive] Personal information about a fictional participant.\n\n"
        "[voice] A fictional writing style sample.\n\n"
        "[ambiguous-status] Technical draft or final status is unclear.\n\n"
        "Technical capacity was measured at 90 mAh with no conditions stated.",
    )
    drain()
    plan = m.CurationPlan.objects.get(family=family, version=version, state="current")
    assert len(plan.eligible_units) == 1
    assert plan.excluded_units
    assert len(plan.pending_units) >= 2
    queue = curation.review_queue(owner[1].id, limit=1)
    assert queue["hidden_count"] and queue["critical_count"] >= 2
    assert len(queue["all"]) >= len(plan.pending_units)
    decision = m.Decision.objects.get(scope=f"unit:{plan.eligible_units[0]}", field="treatment")
    curation.review(
        owner[0],
        decision.id,
        decision.revision,
        "edit",
        value={"treatment": "excluded"},
        rationale="Fictional source is unsuitable.",
        review_seconds=42,
    )
    revised = curation.build_plan(owner[0], family.id, version.id)
    assert str(decision.scope.removeprefix("unit:")) in revised.excluded_units
    assert str(decision.scope.removeprefix("unit:")) not in revised.eligible_units
    assert classification.workload(owner[1].id)[0]["review_seconds"] == 42
    settings.APP = copy.deepcopy(settings.APP)
    settings.APP["classification_model_revision"] = "new-model-revision"
    extraction_service.extract_version(owner[0], version.id)
    drain()
    decision.refresh_from_db()
    assert curation.current_event(decision).actor_id == owner[0].id
    assert not m.Job.objects.filter(kind="classify-unit", state="failed").exists()


def test_dispatch_limit_leaves_visible_version_exception(owner, settings):
    settings.APP = copy.deepcopy(settings.APP)
    settings.APP["classification_max_jobs_per_run"] = 1
    version, run, family = capture(
        owner,
        "Technical fictional first passage.\n\nTechnical fictional second passage.",
    )
    assert run.state == "succeeded"
    assert not m.Job.objects.filter(kind="classify-unit").exists()
    issue = m.Decision.objects.get(
        family=family, scope=f"version:{version.id}", field="treatment", kind="curation"
    )
    assert issue.critical and "configured job bound" in issue.recommendation_rationale
    plan = m.CurationPlan.objects.get(version=version, state="current")
    assert len(plan.pending_units) == 2 and not plan.eligible_units


def test_stale_completion_after_changed_source_never_applies(owner):
    old, run, family = capture(owner, "Technical fictional design note.", item="same")
    attempt = jobs.claim()
    assert attempt is not None
    assert jobs.reserve(attempt.id, "0.01")
    result = classification.OperationalAdapter().execute(
        attempt.job.payload, idempotency_key=str(attempt.job_id)
    )
    new, _, _ = capture(owner, "Technical fictional design note with changed content.", item="same")
    assert new.id != old.id
    assert jobs.finish(attempt.id, result=result)
    assert jobs.deliver(attempt.job_id)
    assert not m.ClassificationResult.objects.filter(job=attempt.job).exists()
    assert not m.CurationPlan.objects.filter(version=old, state="current").exists()
    with pytest.raises(ValueError, match="current source version"):
        curation.build_plan(owner[0], family.id, old.id)
    drain()
    assert m.CurationPlan.objects.filter(version=new, state="current").exists()
    assert m.ClassificationResult.objects.filter(version=new, state="succeeded").exists()


def test_failed_model_is_visible_and_cannot_clear(owner, monkeypatch, settings):
    version, _, family = capture(owner, "Technical fictional evidence.")
    settings.APP = copy.deepcopy(settings.APP)
    settings.APP["max_attempts"] = 1

    def failed(*args, **kwargs):
        from proposal_app.adapters import ProviderFailure

        raise ProviderFailure("provider_error")

    monkeypatch.setattr(classification.OperationalAdapter, "execute", failed)
    assert jobs.work_once()
    job = m.Job.objects.get(kind="classify-unit")
    assert job.state == "failed" and job.stop_reason == "provider_error"
    plan = m.CurationPlan.objects.get(family=family, version=version, state="current")
    assert plan.eligible_units == [] and plan.pending_units
    summary = classification.workload(owner[1].id)[0]
    assert summary["failed_calls"] == 1 and summary["automatic"] == 0


def test_stopped_classification_can_resume_after_attempt_limit(owner, settings):
    version, run, _ = capture(owner, "Technical fictional evidence.")
    job = m.Job.objects.get(kind="classify-unit")
    job.state = "failed"
    job.stop_reason = "attempt_limit"
    job.attempts = settings.APP["max_attempts"]
    job.save(update_fields=["state", "stop_reason", "attempts"])
    resumed = classification.schedule(owner[0], run.id, mock=True)[0]
    assert resumed.id == job.id and resumed.attempts == 0
    assert jobs.work_once()
    resumed.refresh_from_db()
    assert resumed.state == "succeeded"
    assert m.CurationPlan.objects.get(version=version, state="current").eligible_units


def test_blank_legacy_plan_fingerprint_cannot_serve_or_republish(owner):
    version, run, family = capture(owner, "Technical fictional binder note.")
    drain()
    unit = m.ExtractedUnit.objects.get(extraction_run=run)
    inclusion = m.Decision.objects.create(
        family=family,
        scope=f"version:{version.id}",
        field="publication",
        kind="inclusion",
        revision=1,
        status="resolved",
    )
    m.DecisionEvent.objects.create(
        decision=inclusion,
        revision=1,
        actor=owner[0],
        action="approve",
        value={"treatment": "include", "source_version_id": str(version.id)},
        rationale="Fictional local publication demonstration.",
        evidence=[str(unit.id)],
        resolver_revision="test-v1",
    )
    version.source.disposition = "included"
    version.source.save(update_fields=["disposition"])
    generation = workflow.publish(owner[0], family.proposal_id)
    artifact = m.PublicationArtifact.objects.get(generation=generation)
    assert services.eligible_artifacts(owner[0], owner[1].id, [artifact.id]).exists()
    m.CurationPlan.objects.filter(version=version, state="current").update(config_fingerprint="")
    assert not services.eligible_artifacts(owner[0], owner[1].id, [artifact.id]).exists()
    assert classification.workload(owner[1].id)[0]["pending"] == 1
    with pytest.raises(ValueError, match="obsolete model or policy"):
        workflow.publish(owner[0], family.proposal_id)


@pytest.mark.parametrize(
    "setting,value",
    [
        ("classification_max_excerpt_chars", 2000),
        ("classification_max_output_tokens", 800),
        ("classification_numeric_entity_terms", ["fictional-other-subject"]),
    ],
)
def test_classification_input_change_fences_old_result(owner, settings, setting, value):
    version, run, family = capture(owner, "Technical fictional binder note.")
    drain()
    old_plan = m.CurationPlan.objects.get(version=version, state="current")
    settings.APP = copy.deepcopy(settings.APP)
    settings.APP[setting] = value
    assert old_plan.config_fingerprint != curation.config_fingerprint()
    assert classification._current(m.Job.objects.get(kind="classify-unit")) is None
    assert classification.workload(owner[1].id)[0]["pending"] == 1


def test_review_browser_shows_uncapped_workload(owner):
    version, _, family = capture(
        owner, "[voice] Fictional voice sample requiring explicit approval."
    )
    drain()
    client = Client()
    client.force_login(owner[0])
    response = client.get(reverse("review-queue", args=[owner[1].id]))
    assert response.status_code == 200
    body = response.content.decode()
    assert "Current proposal workload" in body
    assert "supported, non-sensitive passages resolved automatically" in body
    assert "voice" in body
    decision = m.Decision.objects.get(family=family, field="treatment", scope__startswith="unit:")
    detail = reverse("review-decision", args=[decision.id])
    assert client.get(detail).status_code == 200
    response = client.post(
        detail,
        {
            "revision": decision.revision,
            "action": "edit",
            "treatment": "excluded",
            "rationale": "Fictional voice sample is not approved for use.",
        },
    )
    assert response.status_code == 302
    event = curation.current_event(decision)
    assert event.review_seconds is not None
    assert m.CurationPlan.objects.get(version=version, state="current").excluded_units


def test_revision_change_requeues_without_losing_human_history(owner, settings):
    version, run, family = capture(owner, "Technical fictional design note.")
    drain()
    unit = m.ExtractedUnit.objects.get(extraction_run=run)
    decision = m.Decision.objects.get(family=family, scope=f"unit:{unit.id}", field="treatment")
    old_event = curation.current_event(decision)
    assert old_event.action == "automatic"
    settings.APP = copy.deepcopy(settings.APP)
    settings.APP["classification_prompt_revision"] = "ingest-source-v2"
    classification.schedule(owner[0], run.id, mock=True)
    decision.refresh_from_db()
    assert decision.status == "unresolved"
    assert (
        str(unit.id)
        not in m.CurationPlan.objects.get(version=version, state="current").eligible_units
    )
    drain()
    decision.refresh_from_db()
    assert curation.current_event(decision).action == "automatic"
    assert curation.current_event(decision).id != old_event.id
    assert m.DecisionEvent.objects.filter(decision=decision, action="automatic").count() == 2
    classification.schedule(owner[0], run.id, mock=True)
    decision.refresh_from_db()
    assert decision.status == "resolved"


def test_cancellation_and_missing_confidence_leave_exception(owner, monkeypatch):
    version, run, family = capture(owner, "Technical fictional evidence.")
    job = m.Job.objects.get(kind="classify-unit")
    services.control_job(owner[0], job.id, "cancel")
    assert not jobs.work_once()
    assert m.CurationPlan.objects.get(version=version, state="current").pending_units

    # A separate source exercises malformed provider output with a known label
    # and no confidence. Its result is recorded, but no fact or clearance applies.
    second, _, _ = capture(owner, "Technical second fictional evidence.")
    original = classification.OperationalAdapter.execute

    def missing(self, payload, *, idempotency_key):
        result = original(self, payload, idempotency_key=idempotency_key)
        value = copy.deepcopy(result.value)
        value["suggestions"]["treatment"]["confidence"] = None
        return CallResult(value, Decimal("0"), result.usage)

    monkeypatch.setattr(classification.OperationalAdapter, "execute", missing)
    drain()
    result = m.ClassificationResult.objects.get(version=second)
    assert result.state == "failed" and result.error == "missing_confidence"
    assert m.CurationPlan.objects.get(version=second, state="current").pending_units
    assert classification.workload(owner[1].id)[0]["failed_calls"] == 1


def test_live_dispatch_is_capped_and_remains_supervised(owner, monkeypatch, settings):
    version, run, family = capture(owner, "Technical fictional evidence.")
    mock_job = m.Job.objects.get(kind="classify-unit")
    services.control_job(owner[0], mock_job.id, "cancel")
    settings.APP = copy.deepcopy(settings.APP)
    settings.APP["classification_estimate_usd_per_call"]["baseline"] = "0.02"
    with pytest.raises(ValueError, match="opt-in"):
        classification.schedule(owner[0], run.id, mock=False, max_spend_usd="0.02")
    monkeypatch.setenv("PROPOSAL_LIVE_CLASSIFICATION_ENABLED", "true")
    with pytest.raises(ValueError, match="per-run cap"):
        classification.schedule(owner[0], run.id, mock=False, max_spend_usd="0.01")
    live_job = classification.schedule(owner[0], run.id, mock=False, max_spend_usd="0.02")[0]
    assert live_job.budget == Decimal("0.02")

    def fake_live(self, payload, *, idempotency_key):
        unit = m.ExtractedUnit.objects.get(pk=payload["unit_id"])
        return CallResult(
            {
                "suggestions": classification._mock(unit),
                "model_revision": "fictional-live",
                "prompt_revision": settings.APP["classification_prompt_revision"],
                "schema_revision": settings.APP["classification_schema_revision"],
                "policy_revision": settings.APP["classification_auto_policy_revision"],
            },
            Decimal("0.02"),
            {"inputTokens": 20, "outputTokens": 5},
        )

    monkeypatch.setattr(classification.OperationalAdapter, "execute", fake_live)
    assert jobs.work_once()
    live_job.refresh_from_db()
    assert live_job.state == "succeeded"
    decision = m.Decision.objects.get(
        family=family, scope=f"unit:{live_job.payload['unit_id']}", field="treatment"
    )
    assert decision.status == "unresolved"
    assert not m.CurationPlan.objects.get(version=version, state="current").eligible_units


def test_malformed_live_response_keeps_charge_and_exception(owner, monkeypatch, settings):
    version, run, _ = capture(owner, "Technical fictional evidence.")
    services.control_job(owner[0], m.Job.objects.get(kind="classify-unit").id, "cancel")
    settings.APP = copy.deepcopy(settings.APP)
    settings.APP["classification_estimate_usd_per_call"]["baseline"] = "0.02"
    monkeypatch.setenv("PROPOSAL_LIVE_CLASSIFICATION_ENABLED", "true")
    job = classification.schedule(owner[0], run.id, mock=False, max_spend_usd="0.02")[0]
    monkeypatch.setattr(
        classification,
        "bedrock_converse_json",
        lambda **kwargs: ({"unexpected": True}, {"inputTokens": 12}),
    )
    assert jobs.work_once()
    job.refresh_from_db()
    result = m.ClassificationResult.objects.get(job=job)
    assert job.state == "succeeded" and result.error == "malformed_response"
    assert m.UsageReservation.objects.get(attempt__job=job).actual == Decimal("0.02")
    assert m.CurationPlan.objects.get(version=version, state="current").pending_units


def test_core_policy_rejects_unsafe_automatic_treatment(owner, settings):
    version, run, family = capture(owner, "[sensitive] Personal information in fictional text.")
    drain()
    unit = m.ExtractedUnit.objects.get(extraction_run=run)
    decision = m.Decision.objects.get(family=family, scope=f"unit:{unit.id}", field="treatment")
    with pytest.raises(ValueError, match="current-policy"):
        curation.automatic_resolution(
            owner[0],
            decision.id,
            decision.revision,
            value={"treatment": "full"},
            rationale="Unsafe attempted clearance",
            evidence=[str(unit.id)],
            resolver_revision=settings.APP["classification_auto_policy_revision"],
            allow_treatment=True,
        )
    assert (
        str(unit.id) in m.CurationPlan.objects.get(version=version, state="current").excluded_units
    )


def test_local_artifact_and_evidence_packet_contain_only_eligible_bytes(owner, settings):
    version, run, family = capture(
        owner,
        "Technical fictional binder note safe for inclusion.\n\n"
        "[sensitive] Personal information about a fictional participant.",
    )
    drain()
    plan = m.CurationPlan.objects.get(version=version, state="current")
    assert len(plan.eligible_units) == 1 and len(plan.excluded_units) == 1
    units = list(m.ExtractedUnit.objects.filter(extraction_run=run))
    inclusion = m.Decision.objects.create(
        family=family,
        scope=f"version:{version.id}",
        field="publication",
        kind="inclusion",
        revision=1,
        status="resolved",
    )
    m.DecisionEvent.objects.create(
        decision=inclusion,
        revision=1,
        actor=owner[0],
        action="approve",
        value={"treatment": "include", "source_version_id": str(version.id)},
        rationale="Fictional local publication demonstration.",
        evidence=[str(unit.id) for unit in units],
        resolver_revision="test-v1",
    )
    version.source.disposition = "included"
    version.source.save(update_fields=["disposition"])
    generation = workflow.publish(owner[0], family.proposal_id)
    artifacts = list(m.PublicationArtifact.objects.filter(generation=generation, eligible=True))
    assert len(artifacts) == 1 and str(artifacts[0].unit_id) in plan.eligible_units
    published = LocalObjectStorage(settings.LOCAL_STORAGE_ROOT).get(artifacts[0].blob.storage_key)
    assert b"binder note" in published and b"Personal information" not in published
    session = services.create_draft(owner[0], owner[1].id, "Fictional draft")
    workflow.pin_evidence(owner[0], session.id, artifacts[0].id)
    draft = workflow.generate(owner[0], session.id, "Summarize the binder note")
    packet = str(draft.packet.payload)
    assert "binder note" in packet and "Personal information" not in packet
    assert "Personal information" not in draft.text
    settings.APP = copy.deepcopy(settings.APP)
    settings.APP["classification_prompt_revision"] = "changed-after-publication"
    assert workflow.search(owner[0], owner[1].id, "binder") == []
    assert not services.eligible_artifacts(owner[0], owner[1].id, [artifacts[0].id]).exists()
    with pytest.raises(ValueError, match="obsolete model or policy"):
        workflow.publish(owner[0], family.proposal_id)


def test_contradictory_measurements_and_unsupported_claim_stay_pending(owner, monkeypatch):
    version, run, family = capture(
        owner,
        "Technical capacity was measured at 90 mAh in a fictional cell.\n\n"
        "Technical capacity was measured at 110 mAh in a fictional cell.",
    )
    drain()
    conflict = m.Decision.objects.get(
        family=family, scope="entity:capacity-mah", field="conditions", kind="curation"
    )
    assert conflict.critical and len(conflict.recommendation_evidence) == 2
    plan = m.CurationPlan.objects.get(version=version, state="current")
    assert not plan.eligible_units and len(plan.pending_units) == 2

    second, _, _ = capture(owner, "Technical fictional note without a measurement.")
    original = classification.OperationalAdapter.execute

    def unsupported(self, payload, *, idempotency_key):
        result = original(self, payload, idempotency_key=idempotency_key)
        value = copy.deepcopy(result.value)
        value["suggestions"]["claim_type"].update(
            value="measurement", quote="999 mAh", confidence=1.0
        )
        return CallResult(value, Decimal("0"), result.usage)

    monkeypatch.setattr(classification.OperationalAdapter, "execute", unsupported)
    drain()
    result = m.ClassificationResult.objects.get(version=second)
    assert result.error == "unsupported_quote"
    assert m.CurationPlan.objects.get(version=second, state="current").pending_units


def test_read_only_local_folder_sync_to_current_plan(owner, monkeypatch, tmp_path):
    root = tmp_path / "2025" / "P-05b"
    root.mkdir(parents=True)
    source_file = root / "fictional.txt"
    original = b"Technical fictional binder stability note."
    source_file.write_bytes(original)
    proposal = m.Proposal.objects.create(collection=owner[1], identifier="P-05b")
    scope = m.SourceScope.objects.create(
        collection=owner[1],
        connector="local",
        tenant="local",
        site="local",
        drive=str(root.anchor),
        root_item=str(root.resolve()),
        proposal=proposal,
        year=2025,
    )
    monkeypatch.setattr(source_sync, "_scope_lock", lambda _: None)
    monkeypatch.setattr(source_sync, "_scope_unlock", lambda _: None)
    adapter = source_sync.LocalSourceAdapter(root)
    first = source_sync.sync_scope(scope, adapter)
    assert first.state == "completed" and first.counts["snapshots"] == 1
    version = m.SourceVersion.objects.get(source__collection=owner[1])
    extraction_service.extract_version(owner[0], version.id)
    drain()
    assert m.CurationPlan.objects.get(version=version, state="current").eligible_units
    assert source_file.read_bytes() == original
    second = source_sync.sync_scope(scope, adapter)
    assert second.counts["snapshots"] == 0
    extraction_service.extract_version(owner[0], version.id)
    assert m.SourceVersion.objects.count() == 1
    assert m.Job.objects.filter(kind="classify-unit").count() == 1
    source_file.write_bytes(b"Technical fictional binder note with changed content.")
    third = source_sync.sync_scope(scope, adapter)
    assert third.counts["snapshots"] == 1
    new_version = m.SourceVersion.objects.order_by("-observed_at").first()
    assert new_version.id != version.id
    assert not m.CurationPlan.objects.filter(version=version, state="current").exists()
    extraction_service.extract_version(owner[0], new_version.id)
    drain()
    assert m.CurationPlan.objects.get(version=new_version, state="current").eligible_units


def test_operator_demo_uses_real_capture_extraction_worker_and_review(owner, monkeypatch, settings):
    monkeypatch.setattr(source_sync, "_scope_lock", lambda _: None)
    monkeypatch.setattr(source_sync, "_scope_unlock", lambda _: None)
    fixture = (
        settings.ROOT / settings.APP["classification_demo_source_root"] / "fictional_source.txt"
    )
    original = fixture.read_bytes()
    output = io.StringIO()
    call_command("fixture_ai_ingest", stdout=output)
    assert "captured=1" in output.getvalue() and "queued=" in output.getvalue()
    drain()
    collection = m.Collection.objects.get(name="Synthetic AI ingestion")
    summary = classification.workload(collection.id)[0]
    assert summary["discovered"] == 1 and summary["units"] == 6
    assert summary["automatic"] == 1 and summary["included"] == 1
    assert summary["excluded"] == 1 and summary["pending"] == 4
    assert summary["exceptions"] >= 6
    assert fixture.read_bytes() == original
    call_command("fixture_ai_ingest", stdout=io.StringIO())
    assert m.Job.objects.filter(collection=collection, kind="classify-unit").count() == 6
