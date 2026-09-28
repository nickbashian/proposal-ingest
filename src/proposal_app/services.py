"""Authorized database services. No legacy files are written by the application."""

import hashlib
import json
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from . import models as m
from .storage import LocalObjectStorage


def authorize(user, collection_id):
    if (
        not user.is_authenticated
        or not user.is_active
        or not m.Identity.objects.filter(user=user, allowed=True).exists()
    ):
        raise PermissionDenied
    if not m.CollectionAccess.objects.filter(user=user, collection_id=collection_id).exists():
        raise PermissionDenied


def owned(user, model, object_id):
    """Resolve ownership from the parent chain, never from submitted owner/collection IDs."""
    obj = model.objects.filter(pk=object_id).first()
    if obj is None:
        raise Http404
    session = (
        obj
        if isinstance(obj, m.DraftSession)
        else (obj.revision.session if isinstance(obj, m.DraftExport) else obj.session)
    )
    authorize(user, session.collection_id)
    if session.owner_id != user.pk or session.deleted_at:
        raise Http404
    return obj


@transaction.atomic
def create_job(user, collection_id, key, *, kind="fixture", payload=None):
    authorize(user, collection_id)
    job, created = m.Job.objects.get_or_create(
        collection_id=collection_id,
        key=key,
        defaults={
            "creator": user,
            "kind": kind,
            "payload": payload or {},
            "budget": Decimal(settings.APP["job_limit_usd"]),
        },
    )
    if created:
        m.AuditRecord.objects.create(actor=user, action="job.created", object_id=job.id)
    return job


@transaction.atomic
def control_job(user, job_id, action):
    job = m.Job.objects.select_for_update().get(pk=job_id)
    authorize(user, job.collection_id)
    if action not in {"pause", "resume", "cancel"}:
        raise ValueError("Unknown action")
    if job.state in {"succeeded", "canceled", "failed"}:
        raise ValueError("Terminal jobs cannot be restarted")
    if action == "resume":
        if job.state not in {"paused", "budget_stopped", "quota_stopped", "disabled"}:
            raise ValueError("Job is not stopped")
        job.state = (
            "delivering" if job.state == "paused" and job.resume_state == "delivering" else "queued"
        )
        job.resume_state = ""
    else:
        if action == "pause" and job.state != "paused":
            job.resume_state = job.state
        job.state = "paused" if action == "pause" else "canceled"
    if job.lease_token:
        m.Attempt.objects.filter(token=job.lease_token, state__in=["claimed", "dispatched"]).update(
            state=job.state, finished_at=timezone.now()
        )
        m.UsageReservation.objects.filter(attempt__token=job.lease_token, state="reserved").update(
            state="unknown"
        )
    job.lease_token = None
    job.lease_until = None
    job.save()
    m.AuditRecord.objects.create(actor=user, action="job." + action, object_id=job.id)
    return job


@transaction.atomic
def create_draft(user, collection_id, title):
    authorize(user, collection_id)
    return m.DraftSession.objects.create(owner=user, collection_id=collection_id, title=title)


@transaction.atomic
def revise_draft(user, session_id, expected_revision, text, packet_id=None):
    session = owned(user, m.DraftSession, session_id)
    session = m.DraftSession.objects.select_for_update().get(pk=session.id)
    if session.deleted_at or session.revision != expected_revision:
        raise ValueError("Draft changed; refresh before editing")
    if packet_id:
        packet = owned(user, m.EvidencePacket, packet_id)
        if packet.session_id != session.id:
            raise ValueError("Evidence belongs to another session")
    else:
        packet = m.EvidencePacket.objects.create(session=session, policy_revision="foundation-v1")
    session.revision += 1
    session.save()
    revision = m.DraftRevision.objects.create(
        session=session, number=session.revision, packet=packet, text=text
    )
    m.AuditRecord.objects.create(actor=user, action="draft.revised", object_id=revision.id)
    return revision


@transaction.atomic
def draft_action(user, model, object_id, action, *, text="", expected_revision=0):
    obj = owned(user, model, object_id)
    session = (
        obj
        if model is m.DraftSession
        else (obj.revision.session if model is m.DraftExport else obj.session)
    )
    session = m.DraftSession.objects.select_for_update().get(pk=session.id)
    if session.deleted_at:
        raise Http404
    if action == "read":
        return obj
    if action == "delete" and model is m.DraftSession:
        session.deleted_at = timezone.now()
        session.save()
        m.AuditRecord.objects.create(actor=user, action="draft.deleted", object_id=session.id)
        return session
    if action == "update" and model is m.DraftSession:
        return revise_draft(user, session.id, expected_revision, text)
    if action == "export":
        revision = (
            obj
            if model is m.DraftRevision
            else m.DraftRevision.objects.filter(session=session).order_by("-number").first()
        )
        if revision is None:
            raise ValueError("No saved revision")
        return m.DraftExport.objects.create(revision=revision, text=revision.text)
    if action == "regenerate":
        # Ownership is enforced now; model generation is MVP-02/07.
        raise ValueError("Draft generation adapter is not enabled")
    raise ValueError("Unsupported operation")


@transaction.atomic
def observe_source(
    user,
    collection_id,
    *,
    identity,
    path,
    observation_key,
    content,
    proposal,
    family,
    upstream_version=None,
    etag=None,
):
    authorize(user, collection_id)
    source, _ = m.SourceItem.objects.get_or_create(
        **identity, defaults={"collection_id": collection_id, "display_path": path}
    )
    if source.collection_id != collection_id:
        raise PermissionDenied
    source.display_path = path
    source.save(update_fields=["display_path"])
    digest = hashlib.sha256(content).hexdigest()
    key = LocalObjectStorage(
        settings.LOCAL_STORAGE_ROOT, require_durable=settings.MODE == "production"
    ).put_immutable(digest, content)
    blob, _ = m.ContentBlob.objects.get_or_create(
        sha256=digest, defaults={"size": len(content), "storage_key": key}
    )
    if not blob.storage_key:
        blob.storage_key = key
        blob.save(update_fields=["storage_key"])
    version, _ = m.SourceVersion.objects.get_or_create(
        source=source,
        observation_key=observation_key,
        defaults={
            "blob": blob,
            "upstream_version": upstream_version,
            "etag": etag,
            "observed_path": path,
        },
    )
    if (
        version.blob_id != blob.id
        or version.upstream_version != upstream_version
        or version.etag != etag
    ):
        raise ValueError("Observation identity cannot be rewritten")
    proposal_obj, _ = m.Proposal.objects.get_or_create(
        collection_id=collection_id, identifier=proposal
    )
    family_obj, _ = m.VersionFamily.objects.get_or_create(proposal=proposal_obj, key=family)
    m.ProposalMembership.objects.get_or_create(source=source, family=family_obj)
    if m.SourceVersion.objects.filter(source=source).exclude(pk=version.pk).exists():
        latest = (
            m.SourceVersion.objects.filter(source=source)
            .order_by("-observed_at", "-created_at", "-id")
            .first()
        )
        if latest and latest.pk == version.pk:
            m.CurationPlan.objects.filter(version__source=source, state="current").exclude(
                version=version
            ).update(state="invalidated")
            m.PublicationArtifact.objects.filter(
                unit__version__source=source, eligible=True
            ).exclude(unit__version=version).update(eligible=False)
    return version


@transaction.atomic
def import_legacy(user, collection_id, path: Path):
    """Read-only staging boundary: legacy hashes never invent upstream source identity."""
    authorize(user, collection_id)
    raw = path.read_bytes()
    records = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if any(not isinstance(record, dict) for record in records):
        raise ValueError("Legacy records must be JSON objects")
    result, _ = m.LegacyImport.objects.get_or_create(
        collection_id=collection_id,
        sha256=hashlib.sha256(raw).hexdigest(),
        defaults={"records": records},
    )
    return result


def eligible_artifacts(user, collection_id, ids):
    authorize(user, collection_id)
    if settings.APP["publication_hold"]:
        return m.PublicationArtifact.objects.none()
    candidates = m.PublicationArtifact.objects.filter(
        id__in=ids,
        eligible=True,
        generation__state="active",
        generation__proposal__collection_id=collection_id,
    )
    from .classification import _latest
    from .curation import config_fingerprint, summary_support_current

    valid = []
    for artifact in candidates.select_related(
        "unit__version__source", "decision_event__decision__family", "generation"
    ):
        family = artifact.decision_event.decision.family
        version = artifact.unit.version
        plans = m.CurationPlan.objects.filter(family=family, version=version)
        if (
            not _latest(version)
            or version.source.disposition == "excluded"
            or artifact.decision_event.decision.revision != artifact.decision_event.revision
            or (artifact.generation.fingerprint and artifact.index_state != "indexed")
        ):
            continue
        if plans.exists():
            plan = plans.filter(
                state="current", extraction_run=artifact.unit.extraction_run
            ).first()
            if plan is None or plan.config_fingerprint != config_fingerprint():
                continue
            if artifact.kind == "summary":
                if not any(
                    summary.get("decision_event_id") == str(artifact.decision_event_id)
                    and summary.get("source_units") == artifact.source_unit_ids
                    and str(artifact.unit_id) in artifact.source_unit_ids
                    and hashlib.sha256(summary["text"].encode("utf-8")).hexdigest()
                    == artifact.blob.sha256
                    and summary_support_current(plan, summary)
                    for summary in plan.derived_summaries
                ):
                    continue
            elif str(artifact.unit_id) not in plan.eligible_units or (
                artifact.generation.fingerprint
                and hashlib.sha256(artifact.unit.text.encode("utf-8")).hexdigest()
                != artifact.blob.sha256
            ):
                continue
        elif m.ClassificationResult.objects.filter(family=family, unit=artifact.unit).exists():
            continue
        valid.append(artifact.id)
    return candidates.filter(id__in=valid)


def factual_artifacts(user, collection_id, ids):
    """Keep legacy factual units and current plan-approved classified passages."""
    eligible = eligible_artifacts(user, collection_id, ids)
    valid = []
    for artifact in eligible.select_related("unit", "decision_event__decision__family"):
        if (
            artifact.kind == "summary"
            or artifact.unit.support_kind == "factual"
            or m.CurationPlan.objects.filter(
                family=artifact.decision_event.decision.family,
                version=artifact.unit.version,
                extraction_run=artifact.unit.extraction_run,
                state="current",
            ).exists()
        ):
            valid.append(artifact.id)
    return eligible.filter(id__in=valid)


@transaction.atomic
def append_decision(user, decision_id, expected_revision, *, value, rationale, evidence):
    decision = (
        m.Decision.objects.select_for_update()
        .select_related("family__proposal")
        .get(pk=decision_id)
    )
    authorize(user, decision.family.proposal.collection_id)
    if decision.revision != expected_revision:
        raise ValueError("Decision changed; refresh before editing")
    decision.revision += 1
    event = m.DecisionEvent.objects.create(
        decision=decision,
        revision=decision.revision,
        actor=user,
        value=value,
        rationale=rationale,
        evidence=evidence,
        resolver_revision="human-foundation-v1",
    )
    decision.save(update_fields=["revision"])
    m.AuditRecord.objects.create(actor=user, action="decision.recorded", object_id=event.id)
    return event
