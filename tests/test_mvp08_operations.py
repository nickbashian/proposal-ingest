"""MVP-08-B operational visibility and privacy contracts."""

import uuid
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from proposal_app import models as m

pytestmark = pytest.mark.django_db


def member(username, collection):
    user = get_user_model().objects.create_user(username=username)
    m.Identity.objects.create(user=user, issuer="local", subject=username, allowed=True)
    m.CollectionAccess.objects.create(collection=collection, user=user)
    return user


def job(collection, user, key, kind, state, reason=""):
    return m.Job.objects.create(
        collection=collection,
        creator=user,
        key=key,
        kind=kind,
        state=state,
        stop_reason=reason,
        attempts=2,
        budget=Decimal("0.300000"),
        payload={"secret": "PRIVATE-PAYLOAD"},
        result={"raw": "PRIVATE-RESULT"},
    )


def test_operations_shows_persisted_restart_budget_outage_and_costs():
    collection = m.Collection.objects.create(name="Fixture operations")
    user = member("operator", collection)
    resumed = job(collection, user, "private-key", "classify-unit", "queued")
    job(collection, user, "quota-key", "classify-unit", "quota_stopped", "provider_quota")
    job(
        collection,
        user,
        "budget-key",
        "draft-generation",
        "budget_stopped",
        "reservation_exceeds_limit",
    )
    job(collection, user, "outage-key", "publication", "failed", "provider_unavailable")
    attempt = m.Attempt.objects.create(job=resumed, number=2, token=uuid.uuid4(), state="unknown")
    m.UsageReservation.objects.create(
        attempt=attempt,
        reserved=Decimal("0.300000"),
        charged=Decimal("0.300000"),
        actual=None,
        state="unknown",
        usage={"response": "PRIVATE-PROVIDER-RESPONSE"},
    )
    client = Client()
    client.force_login(user)
    response = client.get(f"/collections/{collection.id}/operations/")
    assert response.status_code == 200
    body = response.content.decode()
    for item in ("queued", "quota_stopped", "budget_stopped", "provider_unavailable"):
        assert item in body
    assert "0.300000" in body
    assert "Not reported" in body
    assert response.context["summary"]["spending"][0]["unreported"] == 1
    for secret in ("PRIVATE-PAYLOAD", "PRIVATE-RESULT", "PRIVATE-PROVIDER-RESPONSE", "private-key"):
        assert secret not in body


def test_operations_scopes_collection_and_private_draft_jobs():
    collection = m.Collection.objects.create(name="First collection")
    other = m.Collection.objects.create(name="Other collection")
    owner = member("owner", collection)
    colleague = member("colleague", collection)
    outsider = member("outsider", other)
    job(collection, owner, "owner-secret", "draft-generation", "failed", "private_stop")
    job(collection, owner, "public-key", "classify-unit", "succeeded")
    job(other, outsider, "other-key", "publication", "failed", "other_stop")
    client = Client()
    client.force_login(colleague)
    response = client.get(f"/collections/{collection.id}/operations/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "classify-unit" in body
    assert "private_stop" not in body
    assert "other_stop" not in body
    assert client.get(f"/collections/{other.id}/operations/").status_code == 403
    client.logout()
    assert client.get(f"/collections/{collection.id}/operations/").status_code == 401
