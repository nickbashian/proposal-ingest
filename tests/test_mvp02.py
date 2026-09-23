"""MVP-02 acceptance: complete synthetic local product workflow."""

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, urlunparse

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.http import Http404
from django.test import Client
from django.test.utils import CaptureQueriesContext
from playwright.sync_api import sync_playwright

from scripts import dev
from proposal_app import jobs, models as m, services, workflow
from proposal_app.adapters import (
    DeterministicDraftingAdapter,
    FixtureSliceAdapter,
    ProviderFailure,
    adapter_for,
)
from proposal_app.storage import LocalObjectStorage

pytestmark = pytest.mark.django_db

EXCLUDED_TEXT = "EXCLUDED-FIXTURE-PASSAGE"
VOICE_TEXT = "We envision a confident future"
FACT_TEXT = "retained 92% of its initial capacity after 500 cycles"


@pytest.fixture
def slice_owner(settings, tmp_path):
    settings.LOCAL_STORAGE_ROOT = tmp_path / "objects"
    user = get_user_model().objects.create_user(username="fixture-owner")
    m.Identity.objects.create(user=user, issuer="local", subject="fixture-owner", allowed=True)
    collection = m.Collection.objects.create(name="Synthetic MVP-02 collection")
    m.CollectionAccess.objects.create(collection=collection, user=user)
    return user, collection


def import_slice(user, collection):
    job = workflow.enqueue_fixture_import(user, collection.id)
    assert jobs.work_once()
    job.refresh_from_db()
    assert job.state == "succeeded"
    assert job.result["import"]["source_count"] == 3
    return job


def approve_and_publish(user, collection):
    decision = m.Decision.objects.get(
        family__proposal__collection=collection, revision=0, kind="inclusion"
    )
    workflow.answer_inclusion(user, decision.id, 0, "include")
    return workflow.publish(user, decision.family.proposal_id)


def child_environment(storage_root=None):
    database = connection.settings_dict
    authority = (
        f"{quote(database['USER'], safe='')}:{quote(database['PASSWORD'], safe='')}@"
        f"{database['HOST']}:{database['PORT']}"
    )
    env = dict(os.environ)
    env["DATABASE_URL"] = urlunparse(("postgresql", authority, "/" + database["NAME"], "", "", ""))
    env["PROPOSAL_LOCAL_AUTH_ENABLED"] = "true"
    if storage_root:
        env["PROPOSAL_LOCAL_STORAGE_ROOT"] = str(storage_root)
    return env


def test_complete_local_services_exclusion_revisions_and_idempotency(slice_owner, settings):
    user, collection = slice_owner
    first_job = import_slice(user, collection)
    assert workflow.enqueue_fixture_import(user, collection.id).id == first_job.id
    assert m.SourceItem.objects.count() == 3
    assert set(m.SourceItem.objects.values_list("disposition", flat=True)) == {
        "awaiting_decision",
        "excluded",
        "included",
    }
    assert set(m.ExtractedUnit.objects.values_list("support_kind", flat=True)) == {
        "factual",
        "voice",
    }
    proposal = m.Proposal.objects.get(collection=collection)
    with pytest.raises(ValueError, match="Answer all inclusion"):
        workflow.publish(user, proposal.id)

    generation = approve_and_publish(user, collection)
    assert workflow.publish(user, proposal.id).id == generation.id
    assert m.PublicationGeneration.objects.count() == 1
    artifacts = list(
        m.PublicationArtifact.objects.filter(generation=generation).select_related("unit", "blob")
    )
    assert len(artifacts) == 2
    publication_bytes = b"\n".join(
        LocalObjectStorage(settings.LOCAL_STORAGE_ROOT).get(artifact.blob.storage_key)
        for artifact in artifacts
    )
    assert FACT_TEXT.encode() in publication_bytes
    assert VOICE_TEXT.encode() in publication_bytes
    assert EXCLUDED_TEXT.encode() not in publication_bytes

    approved_source = m.SourceItem.objects.get(
        disposition="included", sourceversion__extractedunit__support_kind="factual"
    )
    later_version = services.observe_source(
        user,
        collection.id,
        identity={
            "connector": approved_source.connector,
            "tenant": approved_source.tenant,
            "site": approved_source.site,
            "drive": approved_source.drive,
            "item": approved_source.item,
        },
        path=approved_source.display_path,
        observation_key="unreviewed-later-version",
        content=b"A later synthetic observation.",
        proposal=proposal.identifier,
        family=m.VersionFamily.objects.get(proposal=proposal).key,
        upstream_version="unreviewed-later-version",
    )
    m.ExtractedUnit.objects.create(
        version=later_version,
        extractor_revision="synthetic-structured-v1",
        key="unreviewed-later-unit",
        locator={"section": "Later", "paragraph": 1},
        text="UNREVIEWED-LATER-PASSAGE must wait for another decision.",
        support_kind="factual",
    )
    assert workflow.publish(user, proposal.id).id == generation.id
    assert not workflow.search(user, collection.id, "UNREVIEWED-LATER-PASSAGE")

    results = workflow.search(user, collection.id, "capacity 500 cycles")
    assert len(results) == 1
    assert FACT_TEXT in results[0]["text"]
    assert all(result["support_kind"] == "factual" for result in results)
    assert not workflow.search(user, collection.id, "confident future")

    session = services.create_draft(user, collection.id, "Evidence-backed draft")
    workflow.pin_evidence(user, session.id, results[0]["artifact_id"])
    voice_artifact = next(
        artifact for artifact in artifacts if artifact.unit.support_kind == "voice"
    )
    with pytest.raises(Http404):
        workflow.pin_evidence(user, session.id, voice_artifact.id)
    generated = workflow.generate(user, session.id, "Summarize the cycling result.")
    packet_text = json.dumps(generated.packet.payload)
    assert FACT_TEXT in packet_text
    assert EXCLUDED_TEXT not in packet_text
    assert VOICE_TEXT not in packet_text
    assert generated.model_revision == "deterministic-local-v1"
    assert f"/artifacts/{results[0]['artifact_id']}/" in generated.text

    edited_text = generated.text.replace("92%", "91%") + "\nUser-authored bridge sentence."
    edited = workflow.edit(user, session.id, 1, edited_text)
    regenerated = workflow.generate(user, session.id, "Refresh the supported result.")
    assert regenerated.number == 3
    assert "User-authored bridge sentence." in regenerated.text
    assert "Refresh the supported result." in regenerated.text
    assert regenerated.text.count("## Factual evidence") == 1
    assert "91%" not in regenerated.text and "92%" in regenerated.text
    assert m.DraftRevision.objects.get(pk=edited.id).text == edited_text
    assert m.DraftRevision.objects.filter(session=session).count() == 3

    export_base_url = "https://app.example.test/"
    _, markdown, markdown_extension = workflow.export(user, session.id, "markdown", export_base_url)
    _, plain, plain_extension = workflow.export(user, session.id, "text", export_base_url)
    assert markdown_extension == "md" and plain_extension == "txt"
    assert "](https://app.example.test/artifacts/" in markdown
    assert "Source:" in plain and ": https://app.example.test/artifacts/" in plain
    assert "<!-- proposal-evidence:" not in markdown
    assert "<!-- proposal-evidence:" not in plain

    client = Client()
    client.force_login(user)
    artifact_response = client.get(results[0]["source_url"])
    assert artifact_response.status_code == 200
    assert FACT_TEXT.encode() in artifact_response.content
    assert b"section Results, paragraph 2" in artifact_response.content


def test_fixture_slice_command_is_idempotent():
    call_command("fixture_slice")
    call_command("fixture_slice")
    assert m.Collection.objects.filter(name="Synthetic product slice").count() == 1
    assert m.Job.objects.filter(kind="fixture-slice").count() == 1


def test_fixture_slice_is_disabled_outside_local_mode(slice_owner, settings):
    user, collection = slice_owner
    settings.MODE = "production"
    with pytest.raises(ValueError, match="local only"):
        workflow.enqueue_fixture_import(user, collection.id)
    with pytest.raises(ProviderFailure, match="adapter_disabled"):
        adapter_for("fixture-slice")
    with pytest.raises(ProviderFailure, match="adapter_disabled"):
        FixtureSliceAdapter().execute(
            {"fixture_revision": settings.APP["fixture_slice_revision"]},
            idempotency_key="production-disabled",
        )
    assert not m.Job.objects.exists()


def test_delivery_rechecks_local_mode_and_malformed_items(slice_owner, settings):
    user, collection = slice_owner
    valid_job = workflow.enqueue_fixture_import(user, collection.id)
    result = FixtureSliceAdapter().execute(valid_job.payload, idempotency_key=str(valid_job.id))
    m.Job.objects.filter(pk=valid_job.id).update(state="delivering", result=result.value)
    m.Outbox.objects.create(job=valid_job)
    settings.MODE = "production"
    assert jobs.deliver(valid_job.id)
    valid_job.refresh_from_db()
    assert valid_job.state == "failed" and valid_job.stop_reason == "delivery_invalid"
    assert not m.SourceItem.objects.exists()

    settings.MODE = "local"
    malformed = services.create_job(user, collection.id, "malformed-fixture", kind="fixture-slice")
    bad_result = {
        "revision": settings.APP["fixture_slice_revision"],
        "proposal": "synthetic",
        "family": "synthetic",
        "synthetic": True,
        "items": ["not-an-item"],
    }
    m.Job.objects.filter(pk=malformed.id).update(state="delivering", result=bad_result)
    m.Outbox.objects.create(job=malformed)
    assert jobs.deliver(malformed.id)
    malformed.refresh_from_db()
    assert malformed.state == "failed" and malformed.stop_reason == "delivery_invalid"

    wrong_flag = services.create_job(
        user,
        collection.id,
        "wrong-flag",
        kind="fixture-slice",
        payload={"fixture_revision": settings.APP["fixture_slice_revision"]},
    )
    wrong_flag_result = FixtureSliceAdapter().execute(
        wrong_flag.payload, idempotency_key=str(wrong_flag.id)
    )
    wrong_flag_result.value["synthetic"] = "true"
    m.Job.objects.filter(pk=wrong_flag.id).update(
        state="delivering", result=wrong_flag_result.value
    )
    m.Outbox.objects.create(job=wrong_flag)
    assert jobs.deliver(wrong_flag.id)
    wrong_flag.refresh_from_db()
    assert wrong_flag.state == "failed" and wrong_flag.stop_reason == "delivery_invalid"
    assert not m.SourceItem.objects.exists()


def test_collection_review_rows_are_bound_to_proposal_family(slice_owner):
    user, collection = slice_owner
    import_slice(user, collection)
    original = m.Decision.objects.get(revision=0, kind="inclusion")
    source = m.SourceVersion.objects.get(pk=original.scope.removeprefix("version:")).source
    second_proposal = m.Proposal.objects.create(
        collection=collection, identifier="synthetic-second-proposal"
    )
    second_family = m.VersionFamily.objects.create(
        proposal=second_proposal, key="synthetic-second-family"
    )
    m.ProposalMembership.objects.create(source=source, family=second_family)
    second = m.Decision.objects.create(
        family=second_family,
        scope=original.scope,
        field="publication",
        kind="inclusion",
    )
    services.append_decision(
        user,
        second.id,
        0,
        value={"treatment": "exclude", "support_kind": "factual"},
        rationale="Excluded only from the second family.",
        evidence=[],
    )

    client = Client()
    client.force_login(user)
    response = client.get(f"/collections/{collection.id}/")
    assert response.status_code == 200
    source_rows = [row for row in response.context["rows"] if row["source"] == source]
    assert {row["family"].id for row in source_rows} == {
        original.family_id,
        second_family.id,
    }
    assert {row["decision"].id for row in source_rows} == {original.id, second.id}
    rows_by_family = {row["family"].id: row for row in source_rows}
    assert rows_by_family[original.family_id]["disposition"] == "awaiting_decision"
    assert rows_by_family[original.family_id]["disposition_reason"] == ""
    assert rows_by_family[second_family.id]["disposition"] == "excluded"
    assert (
        rows_by_family[second_family.id]["disposition_reason"]
        == "Excluded only from the second family."
    )
    assert b"synthetic-second-proposal / synthetic-second-family" in response.content
    assert b"Excluded only from the second family." in response.content


def test_human_decision_correction_immediately_removes_stale_retrieval(slice_owner):
    user, collection = slice_owner
    import_slice(user, collection)
    generation = approve_and_publish(user, collection)
    decision = m.Decision.objects.get(decisionevent__rationale="Explicit MVP-02 inclusion review")
    client = Client()
    client.force_login(user)
    page = client.get(f"/collections/{collection.id}/")
    assert page.status_code == 200
    assert page.content.count(b"Include factual passage") == 1
    factual_artifact = m.PublicationArtifact.objects.get(
        generation=generation, unit__support_kind="factual"
    )

    workflow.answer_inclusion(user, decision.id, 1, "exclude")
    assert not workflow.search(user, collection.id, "capacity 500 cycles")
    assert not m.PublicationArtifact.objects.filter(
        generation=generation, unit__support_kind="factual", eligible=True
    ).exists()
    withdrawn = client.get(f"/artifacts/{factual_artifact.id}/")
    assert b"Withdrawn for new use" in withdrawn.content
    assert FACT_TEXT.encode() in withdrawn.content
    workflow.answer_inclusion(user, decision.id, 2, "include")
    replacement = workflow.publish(user, decision.family.proposal_id)
    assert replacement.id != generation.id and replacement.revision == 2
    assert workflow.search(user, collection.id, "capacity 500 cycles")


def test_decision_is_bound_to_one_reviewed_version(slice_owner):
    user, collection = slice_owner
    import_slice(user, collection)
    decision = m.Decision.objects.get(revision=0)
    reviewed_version = m.SourceVersion.objects.get(pk=decision.scope.removeprefix("version:"))
    source = reviewed_version.source
    later = services.observe_source(
        user,
        collection.id,
        identity={
            "connector": source.connector,
            "tenant": source.tenant,
            "site": source.site,
            "drive": source.drive,
            "item": source.item,
        },
        path=source.display_path,
        observation_key="arrived-before-review",
        content=b"Later unreviewed bytes",
        proposal=decision.family.proposal.identifier,
        family=decision.family.key,
        upstream_version="arrived-before-review",
    )
    m.ExtractedUnit.objects.create(
        version=later,
        extractor_revision="synthetic-structured-v1",
        key="later-before-review",
        locator={"section": "Later", "paragraph": 1},
        text="LATER-BEFORE-REVIEW must not be approved.",
    )
    with CaptureQueriesContext(connection) as queries:
        event = workflow.answer_inclusion(user, decision.id, 0, "include")
    assert any(
        "FOR UPDATE" in query["sql"] and '"proposal_app_proposal"' in query["sql"]
        for query in queries
    )
    assert event.value["source_version_id"] == str(reviewed_version.id)
    assert set(event.evidence) == set(
        str(unit_id)
        for unit_id in m.ExtractedUnit.objects.filter(version=reviewed_version).values_list(
            "id", flat=True
        )
    )
    generation = workflow.publish(user, decision.family.proposal_id)
    published = "\n".join(
        artifact.unit.text
        for artifact in m.PublicationArtifact.objects.filter(generation=generation).select_related(
            "unit"
        )
    )
    assert "LATER-BEFORE-REVIEW" not in published


def test_voice_policy_decision_cannot_be_recast_as_factual(slice_owner):
    user, collection = slice_owner
    import_slice(user, collection)
    voice_event = m.DecisionEvent.objects.get(value__support_kind="voice")
    with pytest.raises(ValueError, match="not editable"):
        workflow.answer_inclusion(user, voice_event.decision_id, 1, "include")

    family = voice_event.decision.family
    voice_version = services.observe_source(
        user,
        collection.id,
        identity={
            "connector": "local-fixture",
            "tenant": f"collection-{collection.id}",
            "site": "typed-review",
            "drive": "typed-review",
            "item": "unresolved-voice",
        },
        path="Synthetic/Voice.txt",
        observation_key="voice-review-v1",
        content=b"Synthetic voice-only passage",
        proposal=family.proposal.identifier,
        family=family.key,
    )
    m.ExtractedUnit.objects.create(
        version=voice_version,
        extractor_revision="synthetic-structured-v1",
        key="voice-only",
        locator={"section": "Voice", "paragraph": 1},
        text="An aspirational statement without factual support.",
        support_kind="voice",
    )
    pending_voice = m.Decision.objects.create(
        family=family,
        scope=f"version:{voice_version.id}",
        field="publication",
        kind="inclusion",
    )
    with pytest.raises(ValueError, match="requires factual passages"):
        workflow.answer_inclusion(user, pending_voice.id, 0, "include")


def test_regeneration_preserves_malformed_evidence_markers():
    adapter = DeterministicDraftingAdapter()
    evidence = {
        "title": "Synthetic source",
        "text": "Measured factual result.",
        "locator_label": "section Results, paragraph 1",
        "source_url": "/artifacts/synthetic/",
        "support_kind": "factual",
    }
    malformed = (
        f"{adapter.evidence_end}\nKeep this text.\n{adapter.evidence_start}\n"
        + adapter._citation(evidence)
    )
    result = adapter.draft(
        {"base_text": malformed, "prior_evidence": [evidence], "evidence": [evidence]},
        "Regenerate safely.",
        idempotency_key="malformed-markers",
    )
    assert malformed in result.value["text"]


def test_invalid_fixture_delivery_fails_once_without_raw_error(slice_owner):
    user, collection = slice_owner
    job = workflow.enqueue_fixture_import(user, collection.id)
    m.Job.objects.filter(pk=job.id).update(state="delivering", result={"private": "bad"})
    m.Outbox.objects.create(job=job)
    assert jobs.deliver(job.id)
    job.refresh_from_db()
    assert job.state == "failed"
    assert job.stop_reason == "delivery_invalid"
    assert job.result == {}
    assert m.Outbox.objects.get(job=job).delivered_at is not None
    assert not m.JobResult.objects.filter(job=job).exists()


def test_unexpected_fixture_delivery_error_fails_once(slice_owner, monkeypatch):
    user, collection = slice_owner
    job = workflow.enqueue_fixture_import(user, collection.id)
    m.Job.objects.filter(pk=job.id).update(state="delivering", result={"synthetic": True})
    m.Outbox.objects.create(job=job)

    def fail_delivery(_job):
        raise OSError("synthetic storage failure")

    monkeypatch.setattr(workflow, "deliver_fixture_import", fail_delivery)
    assert jobs.deliver(job.id)
    job.refresh_from_db()
    assert job.state == "failed"
    assert job.stop_reason == "delivery_error"
    assert job.result == {}
    assert m.Outbox.objects.get(job=job).delivered_at is not None
    assert not m.JobResult.objects.filter(job=job).exists()


def test_revoked_fixture_delivery_fails_closed(slice_owner):
    user, collection = slice_owner
    job = workflow.enqueue_fixture_import(user, collection.id)
    adapter_result = FixtureSliceAdapter().execute(job.payload, idempotency_key=str(job.id))
    m.Job.objects.filter(pk=job.id).update(state="delivering", result=adapter_result.value)
    m.Outbox.objects.create(job=job)
    m.Identity.objects.filter(user=user).update(allowed=False)
    assert jobs.deliver(job.id)
    job.refresh_from_db()
    assert job.state == "failed"
    assert job.stop_reason == "delivery_denied"
    assert not m.SourceItem.objects.exists()


def test_writing_workspace_remains_owner_private(slice_owner):
    owner, collection = slice_owner
    session = services.create_draft(owner, collection.id, "Owner only")
    other = get_user_model().objects.create_user(username="other")
    m.Identity.objects.create(user=other, issuer="local", subject="other", allowed=True)
    m.CollectionAccess.objects.create(collection=collection, user=other)
    anonymous = Client()
    assert anonymous.get(f"/writing/{session.id}/").status_code == 401
    client = Client()
    client.force_login(other)
    assert client.get(f"/writing/{session.id}/").status_code == 404


@pytest.mark.django_db(transaction=True)
def test_fresh_process_retains_decision_and_draft(slice_owner):
    user, collection = slice_owner
    import_slice(user, collection)
    approve_and_publish(user, collection)
    result = workflow.search(user, collection.id, "92% capacity")[0]
    session = services.create_draft(user, collection.id, "Restart persistence")
    workflow.pin_evidence(user, session.id, result["artifact_id"])
    revision = workflow.generate(user, session.id, "Use the measured result.")
    code = f"""
import json, os
os.environ['DJANGO_SETTINGS_MODULE'] = 'proposal_app.settings'
import django
django.setup()
from proposal_app import models as m
session = m.DraftSession.objects.get(pk='{session.id}')
event = m.DecisionEvent.objects.get(rationale='Explicit MVP-02 inclusion review')
revision = m.DraftRevision.objects.get(pk='{revision.id}')
print(json.dumps({{'session_revision': session.revision,
                  'decision_revision': event.decision.revision,
                  'draft_number': revision.number,
                  'packet_items': len(revision.packet.payload)}}))
"""
    process = subprocess.run(
        [sys.executable, "-c", code],
        env=child_environment(),
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(process.stdout) == {
        "session_revision": 1,
        "decision_revision": 1,
        "draft_number": 1,
        "packet_items": 1,
    }


@pytest.mark.django_db(transaction=True)
def test_browser_complete_local_product_slice(slice_owner, settings, live_server, monkeypatch):
    _, collection = slice_owner
    monkeypatch.setattr(settings, "LOCAL_AUTH", True)
    cache = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if not cache:
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "")
        dev._configure_browser_cache()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context()
            page = context.new_page()
            assert page.goto(live_server.url + f"/collections/{collection.id}/").status == 401
            page.goto(live_server.url + "/login/")
            page.get_by_role("button", name="Sign in locally").click()
            page.get_by_role("link", name="Open review and writing workflow").click()
            page.get_by_role("button", name="Import synthetic family").click()
            first_job_url = page.url
            subprocess.run(
                [sys.executable, "scripts/manage.py", "worker", "--once"],
                env=child_environment(settings.LOCAL_STORAGE_ROOT),
                check=True,
                timeout=20,
                capture_output=True,
            )
            page.reload()
            assert "succeeded" in page.locator("body").inner_text()
            page.get_by_role("link", name="Return to collection review").click()
            body = page.locator("body").inner_text()
            assert "awaiting_decision" in body and "excluded" in body and "included" in body
            assert "Voice-only passages" in body
            page.get_by_role("button", name="Include factual passage").click()
            page.get_by_role("button", name="Publish eligible passages", exact=False).click()
            page.get_by_role("button", name="Create writing workspace").click()
            assert "Local deterministic retrieval" in page.locator("body").inner_text()
            assert "Deterministic local drafting" in page.locator("body").inner_text()
            page.get_by_label("Query").fill("capacity 500 cycles")
            page.get_by_role("button", name="Search local evidence").click()
            assert FACT_TEXT in page.locator("body").inner_text()
            artifact_url = page.get_by_role("link", name="Open exact passage").get_attribute("href")
            page.get_by_role("button", name="Pin factual evidence").click()
            page.get_by_role("button", name="Generate deterministic draft").click()
            textarea = page.locator('textarea[name="text"]')
            assert FACT_TEXT in textarea.input_value()
            textarea.fill(textarea.input_value() + "\nUser-authored bridge sentence.")
            page.get_by_role("button", name="Save edit as new revision").click()
            page.get_by_role("button", name="Regenerate as a new revision").click()
            assert "User-authored bridge sentence." in page.locator("body").inner_text()
            if screenshot_path := os.environ.get("MVP02_SCREENSHOT_PATH"):
                path = Path(screenshot_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=path, full_page=True)
            with page.expect_download() as download_info:
                page.get_by_role("button", name="Export Markdown with source links").click()
            download = download_info.value
            assert download.suggested_filename == "draft.md"
            markdown_export = Path(download.path()).read_text(encoding="utf-8")
            assert f"]({live_server.url}/artifacts/" in markdown_export
            assert "<!-- proposal-evidence:" not in markdown_export
            with page.expect_download() as text_download_info:
                page.get_by_role("button", name="Export text with source links").click()
            text_download = text_download_info.value
            assert text_download.suggested_filename == "draft.txt"
            plain_export = Path(text_download.path()).read_text(encoding="utf-8")
            assert f": {live_server.url}/artifacts/" in plain_export
            assert "<!-- proposal-evidence:" not in plain_export

            citation = context.new_page()
            citation.goto(live_server.url + artifact_url)
            assert FACT_TEXT in citation.locator("#passage").inner_text()
            assert citation.locator("#locator").inner_text() == "section Results, paragraph 2"
            citation.close()

            page.get_by_role("link", name="Proposal Knowledge Base").click()
            page.get_by_role("link", name="Open review and writing workflow").click()
            page.get_by_role("button", name="Import synthetic family").click()
            assert page.url == first_job_url
            page.get_by_role("button", name="Sign out").click()
            assert page.goto(live_server.url + f"/collections/{collection.id}/").status == 401
        finally:
            browser.close()
    assert m.SourceItem.objects.count() == 3
