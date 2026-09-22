"""MVP-01 acceptance: PostgreSQL, synthetic identities/data, no live providers."""

import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest
from authlib.integrations.django_client import OAuth
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management import call_command, CommandError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.http import Http404
from django.test import Client
from django.utils import timezone
from joserfc import jwt
from joserfc.jwk import RSAKey

from proposal_app import auth, jobs, models as m, services
from proposal_app.adapters import (
    CallResult,
    FixtureAdapter,
    ProviderFailure,
    capability,
    normalize_error,
)
from proposal_app.storage import LocalObjectStorage

pytestmark = pytest.mark.django_db


@pytest.fixture
def actors(settings, tmp_path):
    settings.LOCAL_STORAGE_ROOT = tmp_path / "objects"
    users = []
    collection = m.Collection.objects.create(name="Synthetic collection")
    for name in ("alice", "bob"):
        user = get_user_model().objects.create_user(username=name)
        m.Identity.objects.create(user=user, issuer="local", subject=name, allowed=True)
        m.CollectionAccess.objects.create(collection=collection, user=user)
        users.append(user)
    return *users, collection


def result(cost="0.001"):
    return CallResult({"synthetic": True}, Decimal(cost), {"requests": 1})


def new_job(actors):
    alice, _, collection = actors
    return services.create_job(alice, collection.id, uuid.uuid4().hex)


@pytest.mark.django_db(transaction=True)
def test_source_identity_and_memberships(actors, settings):
    alice, _, collection = actors
    versions = []
    for item in ("path-a", "path-b"):
        versions.append(
            services.observe_source(
                alice,
                collection.id,
                identity=dict(
                    connector="local", tenant="fixture", site="fixture", drive="fixture", item=item
                ),
                path=item,
                observation_key="observed-1",
                content=b"synthetic identical bytes",
                proposal=item,
                family="family",
            )
        )
    assert versions[0].blob_id == versions[1].blob_id
    assert m.ProposalMembership.objects.count() == 2
    assert m.SourceItem.objects.count() == 2
    assert versions[0].upstream_version is None
    assert (
        LocalObjectStorage(settings.LOCAL_STORAGE_ROOT).get(versions[0].blob.storage_key)
        == b"synthetic identical bytes"
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        m.SourceVersion.objects.create(
            source=versions[0].source, observation_key="observed-1", blob=versions[0].blob
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        m.SourceVersion.objects.create(
            source_id=uuid.uuid4(), observation_key="unknown", blob=versions[0].blob
        )
        connection.check_constraints()
    connection.close()
    assert m.SourceVersion.objects.count() == 2


@pytest.mark.parametrize("kind", ["sessions", "revisions", "packets", "exports"])
@pytest.mark.parametrize("action", ["read", "update", "regenerate", "delete", "export"])
def test_private_objects_all_direct_operations(actors, kind, action):
    alice, bob, collection = actors
    session = services.create_draft(alice, collection.id, "Alice private")
    revision = services.revise_draft(alice, session.id, 0, "Synthetic private draft")
    export = services.draft_action(alice, m.DraftRevision, revision.id, "export")
    objects = {
        "sessions": session,
        "revisions": revision,
        "packets": revision.packet,
        "exports": export,
    }
    obj = objects[kind]
    with pytest.raises(Http404):
        services.draft_action(bob, type(obj), obj.id, action)
    client = Client()
    client.force_login(bob)
    url = f"/drafts/{kind}/{obj.id}/" + ("" if action == "read" else action + "/")
    response = client.get(url) if action == "read" else client.post(url)
    assert response.status_code == 404
    client.force_login(alice)
    assert client.get(f"/drafts/{kind}/{obj.id}/").status_code == 200


def test_collection_auth_revocation_and_anonymous(actors):
    alice, bob, collection = actors
    job = new_job(actors)
    session = services.create_draft(alice, collection.id, "Draft")
    client = Client()
    for path in (
        "/",
        f"/collections/{collection.id}/",
        f"/jobs/{job.id}/",
        f"/drafts/sessions/{session.id}/",
        f"/artifacts/{uuid.uuid4()}/",
    ):
        assert client.get(path).status_code == 401
    client.force_login(bob)
    m.CollectionAccess.objects.filter(user=bob).delete()
    assert client.get(f"/jobs/{job.id}/").status_code == 403
    assert client.get(f"/collections/{collection.id}/").status_code == 403
    m.Identity.objects.filter(user=bob).update(allowed=False)
    assert client.get("/").status_code == 401


def test_local_login_loopback_logout_and_csrf(actors, settings):
    settings.LOCAL_AUTH = True
    client = Client()
    assert (
        client.post(
            "/auth/local/", {"subject": "alice"}, HTTP_HOST="localhost", REMOTE_ADDR="192.0.2.1"
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/auth/local/", {"subject": "alice"}, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1"
        ).status_code
        == 302
    )
    assert client.get("/").status_code == 200
    assert client.post("/logout/").status_code == 302
    assert client.get("/").status_code == 401
    assert (
        client.post(
            "/auth/local/", {"subject": "alice"}, HTTP_HOST="[::1]:8000", REMOTE_ADDR="::1"
        ).status_code
        == 302
    )
    settings.MODE = "production"
    assert (
        client.post("/auth/local/", {"subject": "alice"}, HTTP_HOST="localhost").status_code == 403
    )
    secure_client = Client(enforce_csrf_checks=True)
    assert secure_client.post("/auth/local/", {"subject": "alice"}).status_code == 403


@pytest.mark.parametrize(
    "defect",
    [
        None,
        "issuer",
        "audience",
        "nonce",
        "signature",
        "expired",
        "denied",
        "nonallowlisted",
        "state",
    ],
)
def test_signed_mock_oidc(actors, settings, monkeypatch, defect):
    alice, _, _ = actors
    settings.OIDC_ISSUER = "https://identity.example.test/tenant/v2.0"
    settings.OIDC_CLIENT_ID = "synthetic-client"
    settings.OIDC_REDIRECT_URI = "http://testserver/auth/callback/"
    key = RSAKey.generate_key(2048)
    key.ensure_kid()
    client_app = OAuth().register(
        "entra",
        client_id=settings.OIDC_CLIENT_ID,
        client_secret="synthetic-test-only",
        authorize_url="https://identity.example.test/authorize",
        access_token_url="https://identity.example.test/token",
        client_kwargs={"scope": "openid"},
        issuer=settings.OIDC_ISSUER,
        jwks={"keys": [key.as_dict(private=False)]},
        id_token_signing_alg_values_supported=["RS256"],
    )
    monkeypatch.setattr(auth, "oidc_client", lambda: client_app)
    m.Identity.objects.filter(user=alice).update(
        issuer=settings.OIDC_ISSUER, subject="alice-subject"
    )
    client = Client()
    start = client.get("/auth/start/")
    params = parse_qs(urlparse(start.url).query)
    claims = {
        "iss": settings.OIDC_ISSUER,
        "aud": settings.OIDC_CLIENT_ID,
        "sub": "alice-subject",
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
        "nonce": params["nonce"][0],
    }
    if defect == "issuer":
        claims["iss"] = "https://wrong.example.test"
    if defect == "audience":
        claims["aud"] = "wrong-client"
    if defect == "nonce":
        claims["nonce"] = "wrong-nonce"
    if defect == "expired":
        claims["exp"] = int(time.time()) - 300
    if defect == "nonallowlisted":
        claims["sub"] = "unknown-person"
    signed = jwt.encode(
        {"alg": "RS256", "kid": key.kid},
        claims,
        key if defect != "signature" else RSAKey.generate_key(2048),
    )
    monkeypatch.setattr(
        client_app,
        "fetch_access_token",
        lambda **kwargs: {
            "id_token": signed,
            "access_token": "synthetic-token",
            "token_type": "Bearer",
        },
    )
    response = client.get(
        "/auth/callback/",
        {
            "code": "synthetic-code",
            "state": params["state"][0] if defect != "state" else "wrong",
            **({"error": "access_denied"} if defect == "denied" else {}),
        },
    )
    assert response.status_code == (302 if defect is None else 403)
    assert client.get("/").status_code == (200 if defect is None else 401)


@pytest.mark.parametrize("extra", [{}, {"PROPOSAL_LOCAL_AUTH_ENABLED": "true"}])
def test_production_fails_closed(extra):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("ENTRA_", "OIDC_", "PROPOSAL_"))
    }
    env.update(PROPOSAL_APP_ENV="production", **extra)
    proc = subprocess.run(
        [sys.executable, "scripts/manage.py", "check"], env=env, capture_output=True, text=True
    )
    assert proc.returncode != 0
    assert "ImproperlyConfigured" in proc.stderr


def test_budget_retry_unknown_and_late_cancellation(actors):
    job = new_job(actors)
    attempt = jobs.claim()
    assert jobs.reserve(attempt.id, ".02")
    assert jobs.reserve(attempt.id, ".02") is None
    services.control_job(actors[0], job.id, "cancel")
    attempt.refresh_from_db()
    assert attempt.state == "canceled" and attempt.finished_at is not None
    assert m.UsageReservation.objects.get(attempt=attempt).state == "unknown"
    assert not jobs.finish(attempt.id, result=result(".01"))
    assert not jobs.deliver(job.id)
    assert not m.JobResult.objects.exists()
    assert m.UsageReservation.objects.get().charged == Decimal(".01")
    assert jobs.claim() is None


def test_expired_attempt_retains_cost_and_fences_old_result(actors):
    job = new_job(actors)
    old = jobs.claim()
    jobs.reserve(old.id, ".02")
    m.Job.objects.filter(pk=job.id).update(lease_until=timezone.now() - timedelta(seconds=1))
    new = jobs.claim()
    assert new.number == 2
    assert m.UsageReservation.objects.get(attempt=old).state == "unknown"
    assert not jobs.heartbeat(old.id)
    assert jobs.heartbeat(new.id)
    jobs.reserve(new.id, ".02")
    assert jobs.finish(new.id, result=result())
    assert not jobs.finish(old.id, result=result())
    assert jobs.deliver(job.id)
    assert not jobs.deliver(job.id)
    assert m.JobResult.objects.count() == 1
    assert m.UsageReservation.objects.count() == 2


def test_pause_resume_budget_and_quota(actors):
    job = new_job(actors)
    services.control_job(actors[0], job.id, "pause")
    assert jobs.claim() is None
    services.control_job(actors[0], job.id, "resume")
    attempt = jobs.claim()
    assert jobs.reserve(attempt.id, "6") is None
    job.refresh_from_db()
    assert job.state == "budget_stopped"
    assert job.lease_token is None and job.lease_until is None
    attempt.refresh_from_db()
    assert attempt.state == "budget_stopped" and attempt.finished_at
    services.control_job(actors[0], job.id, "resume")
    attempt = jobs.claim()
    jobs.reserve(attempt.id, ".01")
    jobs.finish(attempt.id, failure=ProviderFailure("quota", quota=True))
    job.refresh_from_db()
    assert job.state == "quota_stopped"


def test_retry_bounded_and_backoff(actors, settings):
    job = new_job(actors)
    for number in range(settings.APP["max_attempts"]):
        attempt = jobs.claim()
        jobs.reserve(attempt.id, ".1")
        jobs.finish(attempt.id, failure=ProviderFailure("timeout", retryable=True, unknown=True))
        assert jobs.claim() is None
        job.refresh_from_db()
        if number + 1 < settings.APP["max_attempts"]:
            assert job.available_at > timezone.now()
            m.Job.objects.filter(pk=job.id).update(available_at=timezone.now())
    assert job.state == "failed"
    assert sum(m.UsageReservation.objects.values_list("charged", flat=True)) == Decimal(".3")
    with pytest.raises(ValueError):
        services.control_job(actors[0], job.id, "resume")


@pytest.mark.django_db(transaction=True)
def test_competing_workers_and_global_budget(actors):
    first, second = new_job(actors), new_job(actors)
    m.BudgetAccount.objects.create(key="setup", limit=Decimal(".01"))

    def claim_and_reserve(_):
        close_old_connections()
        try:
            attempt = jobs.claim()
            if attempt:
                return jobs.reserve(attempt.id, ".01") is not None
            return False
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(claim_and_reserve, range(2))) == 1
    assert m.Attempt.objects.count() == 2
    assert m.UsageReservation.objects.count() == 1
    assert m.BudgetAccount.objects.get(pk="setup").committed == Decimal(".01")
    assert set(m.Job.objects.values_list("state", flat=True)) == {"running", "budget_stopped"}
    assert first.id != second.id


def test_outbox_cancel_before_delivery_and_disabled_adapter(actors):
    job = new_job(actors)
    attempt = jobs.claim()
    jobs.reserve(attempt.id, ".01")
    jobs.finish(attempt.id, result=result())
    services.control_job(actors[0], job.id, "cancel")
    assert not jobs.deliver(job.id)
    other = services.create_job(actors[0], actors[2].id, "disabled", kind="bedrock")
    jobs.work_once()
    other.refresh_from_db()
    assert other.state == "disabled"
    assert not m.UsageReservation.objects.filter(attempt__job=other).exists()


def test_pause_resume_completed_call_does_not_repeat_dispatch(actors):
    job = new_job(actors)
    attempt = jobs.claim()
    jobs.reserve(attempt.id, ".01")
    jobs.finish(attempt.id, result=result())
    services.control_job(actors[0], job.id, "pause")
    services.control_job(actors[0], job.id, "pause")
    assert not jobs.deliver(job.id)
    services.control_job(actors[0], job.id, "resume")
    assert jobs.deliver(job.id)
    job.refresh_from_db()
    assert job.state == "succeeded"
    assert job.attempts == 1


def test_success_clears_old_error_and_canceled_result_is_hidden(actors):
    job = new_job(actors)
    m.Job.objects.filter(pk=job.id).update(stop_reason="old-timeout")
    attempt = jobs.claim()
    jobs.reserve(attempt.id, ".01")
    jobs.finish(attempt.id, result=CallResult({"text": "unpublished-result"}, Decimal(0), {}))
    client = Client()
    client.force_login(actors[0])
    assert b"unpublished-result" not in client.get(f"/jobs/{job.id}/").content
    assert jobs.deliver(job.id)
    job.refresh_from_db()
    assert job.stop_reason == ""
    assert b"unpublished-result" in client.get(f"/jobs/{job.id}/").content


def test_legacy_import_is_read_only_and_idempotent(actors, tmp_path):
    path = tmp_path / "legacy.jsonl"
    raw = json.dumps(
        {"document_id": "content-hash-is-not-source-identity", "human_correction": "keep"}
    ).encode()
    path.write_bytes(raw)
    first = services.import_legacy(actors[0], actors[2].id, path)
    assert first.id == services.import_legacy(actors[0], actors[2].id, path).id
    assert hashlib.sha256(path.read_bytes()).hexdigest() == first.sha256
    assert first.records[0]["human_correction"] == "keep"
    assert m.SourceItem.objects.count() == 0


@pytest.mark.parametrize(
    "payload,status,retry,unknown,quota",
    [
        ({"error": {"code": "TooManyRequests", "message": "private"}}, 429, True, False, False),
        ({"error": {"code": "accessDenied"}}, 403, False, False, False),
        ({"Error": {"Code": "ThrottlingException"}}, 429, True, False, False),
        ({"Error": {"Code": "ServiceQuotaExceededException"}}, 400, False, False, True),
        ({"Error": {"Code": "ModelTimeoutException"}}, 408, True, True, False),
        ({"Error": {"Code": "ModelErrorException"}}, 424, True, True, False),
    ],
)
def test_provider_error_contract(payload, status, retry, unknown, quota):
    error = normalize_error(payload, status)
    assert (error.retryable, error.unknown, error.quota) == (retry, unknown, quota)
    assert "private" not in str(error)


def test_fixture_adapter_and_live_capabilities(actors):
    adapter = FixtureAdapter()
    assert adapter.execute({}, idempotency_key="same") == adapter.execute(
        {}, idempotency_key="same"
    )
    assert adapter.execute({}, idempotency_key="same").value["files"] > 0
    assert not capability("bedrock", {})["enabled"]
    assert capability("bedrock", {})["missing"]
    job = new_job(actors)
    assert jobs.work_once()
    job.refresh_from_db()
    assert job.state == "succeeded"
    assert m.JobResult.objects.get(job=job).value["synthetic"]
    assert m.UsageReservation.objects.get(attempt__job=job).actual == 0


def test_draft_revision_concurrency_and_collection_service_check(actors):
    alice, bob, collection = actors
    session = services.create_draft(alice, collection.id, "Fixture")
    services.revise_draft(alice, session.id, 0, "First")
    with pytest.raises(ValueError):
        services.revise_draft(alice, session.id, 0, "Lost edit")
    m.CollectionAccess.objects.filter(user=bob).delete()
    with pytest.raises(PermissionDenied):
        services.create_draft(bob, collection.id, "Forbidden")


def test_database_guards_immutable_history_and_cross_session_packet(actors):
    alice, _, collection = actors
    first = services.create_draft(alice, collection.id, "One")
    second = services.create_draft(alice, collection.id, "Two")
    revision = services.revise_draft(alice, first.id, 0, "Preserved")
    with pytest.raises(IntegrityError), transaction.atomic():
        m.DraftRevision.objects.create(
            session=second, number=1, packet=revision.packet, text="Wrong session"
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        m.DraftRevision.objects.filter(pk=revision.id).update(text="Overwritten")
    with pytest.raises(IntegrityError), transaction.atomic():
        m.DraftSession.objects.filter(pk=first.id).update(owner=actors[1])
    with pytest.raises(IntegrityError), transaction.atomic():
        m.AuditRecord.objects.all().delete()


def test_decision_optimistic_append_and_eligibility(actors):
    alice, _, collection = actors
    version = services.observe_source(
        alice,
        collection.id,
        identity=dict(
            connector="local", tenant="fixture", site="fixture", drive="fixture", item="one"
        ),
        path="one",
        observation_key="one",
        content=b"fictional",
        proposal="fixture",
        family="fixture",
    )
    family = m.VersionFamily.objects.get()
    with pytest.raises(IntegrityError), transaction.atomic():
        m.ProposalMembership.objects.all().delete()
    unit = m.ExtractedUnit.objects.create(
        version=version, extractor_revision="v1", key="page1", locator={"page": 1}, text="fictional"
    )
    decision = m.Decision.objects.create(family=family, scope="unit", field="reuse", kind="human")
    event = services.append_decision(
        alice,
        decision.id,
        0,
        value={"allowed": True},
        rationale="Synthetic approval",
        evidence=[str(unit.id)],
    )
    with pytest.raises(ValueError):
        services.append_decision(alice, decision.id, 0, value={}, rationale="Stale", evidence=[])
    with pytest.raises(IntegrityError), transaction.atomic():
        m.DecisionEvent.objects.filter(pk=event.id).update(value={"allowed": False})
    generation = m.PublicationGeneration.objects.create(
        proposal=family.proposal, revision=1, state="active"
    )
    curated_blob = m.ContentBlob.objects.create(
        sha256=hashlib.sha256(b"curated excerpt").hexdigest(), size=len(b"curated excerpt")
    )
    artifact = m.PublicationArtifact.objects.create(
        generation=generation, unit=unit, decision_event=event, blob=curated_blob, eligible=True
    )
    assert artifact.blob_id != unit.version.blob_id
    assert services.eligible_artifacts(alice, collection.id, [artifact.id]).count() == 1
    m.PublicationArtifact.objects.filter(pk=artifact.id).update(eligible=False)
    assert not services.eligible_artifacts(alice, collection.id, [artifact.id]).exists()


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1"])
def test_invalid_costs_never_dispatch(actors, value):
    new_job(actors)
    attempt = jobs.claim()
    with pytest.raises(ValueError):
        jobs.reserve(attempt.id, value)
    assert not m.UsageReservation.objects.exists()


def test_operator_revocation_removes_grant_without_creating_collection(actors):
    alice, _, collection = actors
    call_command(
        "allow_identity",
        "alice",
        issuer="local",
        subject="alice",
        collection=collection.name,
        revoke=True,
    )
    assert not m.CollectionAccess.objects.filter(user=alice).exists()
    assert not m.Identity.objects.get(user=alice).allowed
    call_command(
        "allow_identity",
        "alice",
        issuer="local",
        subject="alice",
        collection="does-not-exist",
        revoke=True,
    )
    assert not m.Collection.objects.filter(name="does-not-exist").exists()
    with pytest.raises(CommandError):
        call_command(
            "allow_identity",
            "unknown",
            issuer="local",
            subject="unknown",
            collection="unknown",
            revoke=True,
        )
    assert not get_user_model().objects.filter(username="unknown").exists()


def test_local_storage_immutable_and_rejects_bad_keys(tmp_path):
    storage = LocalObjectStorage(tmp_path / "output")
    content = b"synthetic preserved bytes"
    digest = hashlib.sha256(content).hexdigest()
    assert storage.put_immutable(digest, content) == digest
    assert storage.put_immutable(digest, content) == digest
    assert storage.get(digest) == content
    with pytest.raises(ValueError):
        storage.put_immutable(digest, b"different")
    with pytest.raises(ValueError):
        storage.get("../outside")
    (storage.root / digest).write_bytes(b"corrupted")
    with pytest.raises(ValueError):
        storage.get(digest)


def test_storage_synchronizes_parent_and_installed_object(tmp_path, monkeypatch):
    from proposal_app import storage as module

    root = tmp_path / "nested" / "objects"
    content = b"synthetic durable object"
    digest = hashlib.sha256(content).hexdigest()
    calls = []
    original = module._sync_directory

    def observe(path):
        calls.append((path, (root / digest).exists()))
        original(path)

    monkeypatch.setattr(module, "_sync_directory", observe)
    store = LocalObjectStorage(root)
    store.put_immutable(digest, content)
    assert (tmp_path, False) in calls
    assert calls[-1] == (root, True)
    calls.clear()
    store.put_immutable(digest, content)
    assert calls == [(root, True)]
    monkeypatch.setattr(module, "DIRECTORY_FSYNC", False)
    with pytest.raises(ValueError):
        LocalObjectStorage(root, require_durable=True)


def test_fixture_command_rejects_existing_nonlocal_identity():
    user = get_user_model().objects.create_user(username="fixture-owner")
    m.Identity.objects.create(
        user=user, issuer="https://identity.example.test", subject="not-local", allowed=True
    )
    with pytest.raises(CommandError):
        call_command("fixture_job")
    assert not m.Job.objects.exists()
    assert not m.CollectionAccess.objects.exists()


@pytest.mark.parametrize(
    "query,production,valid",
    [
        ("sslmode=require", False, True),
        ("sslmode=verify-full", True, True),
        ("sslmode=prefer", True, False),
        ("sslmode=verify-full&sslmode=disable", True, False),
        ("unsupported=option", False, False),
    ],
)
def test_database_url_options_fail_closed(query, production, valid):
    env = dict(os.environ)
    env.update(
        PROPOSAL_APP_ENV="production" if production else "local",
        PROPOSAL_LOCAL_AUTH_ENABLED="false",
        DATABASE_URL="postgresql://localhost/synthetic?" + query,
        PROPOSAL_SECRET_KEY=uuid.uuid4().hex + uuid.uuid4().hex,
        OIDC_ISSUER="https://identity.example.test/tenant/v2.0",
        ENTRA_CLIENT_ID="synthetic",
        ENTRA_CLIENT_SECRET="synthetic-test-only",
        ENTRA_REDIRECT_URI="https://app.example.test/auth/callback/",
        PROPOSAL_ALLOWED_HOSTS="app.example.test, other.example.test ",
    )
    code = "import json; from proposal_app import settings; print(json.dumps([settings.DATABASES['default']['OPTIONS'], settings.ALLOWED_HOSTS]))"
    proc = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert (proc.returncode == 0) is valid
    if valid:
        options, hosts = json.loads(proc.stdout)
        assert options["sslmode"] == query.split("=")[1]
        if production:
            assert hosts == ["app.example.test", "other.example.test"]


@pytest.mark.django_db(transaction=True)
def test_competing_claim_and_delivery_single_job(actors):
    job = new_job(actors)

    def execute(_):
        close_old_connections()
        try:
            return jobs.work_once()
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(execute, range(2)))
    assert m.Attempt.objects.filter(job=job).count() == 1
    assert m.JobResult.objects.filter(job=job).count() == 1
