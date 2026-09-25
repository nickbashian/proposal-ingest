"""Curated, generation-scoped publication with exact index reconciliation."""

import hashlib
import json
import math
import os
import uuid

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.http import Http404
from django.utils import timezone

from . import models as m, services
from .classification import _latest
from .curation import config_fingerprint, effective_value, summary_support_current
from .storage import LocalObjectStorage


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def metadata_for(artifact):
    """No source text, path, or neighboring passage may enter KB metadata."""
    attributes = {
        "artifact_id": str(artifact.id),
        "generation_id": str(artifact.generation_id),
        "source_version_id": str(artifact.unit.version_id),
        "source_unit_ids": ",".join(artifact.source_unit_ids),
        "decision_event_id": str(artifact.decision_event_id),
        "kind": artifact.kind,
        "content_sha256": artifact.blob.sha256,
    }
    if not all(
        isinstance(key, str) and isinstance(value, str) for key, value in attributes.items()
    ):
        raise ValueError("Publication metadata must contain string attributes")
    metadata = {"metadataAttributes": attributes}
    if len(_json_bytes(metadata)) > settings.APP["publication_max_metadata_bytes"]:
        raise ValueError("Publication metadata exceeds the S3 sidecar limit")
    return metadata


def _treatment_event(plan, unit_id):
    unit = m.ExtractedUnit.objects.get(pk=unit_id, extraction_run=plan.extraction_run)
    value, event = effective_value(plan.family, plan.version, unit, "treatment")
    if (
        event is None
        or plan.decision_revisions.get(str(event.decision_id)) != event.revision
        or value.get("treatment") not in {"full", "partial"}
        or (value["treatment"] == "partial" and str(unit_id) not in value["selected_units"])
    ):
        raise ValueError("Eligible unit lacks a current treatment decision")
    return event


def _plan_specs(proposal):
    specs = []
    plans = list(
        m.CurationPlan.objects.filter(family__proposal=proposal, state="current")
        .select_related("family", "version__source", "extraction_run")
        .order_by("family_id", "version_id")
    )
    for plan in plans:
        if plan.config_fingerprint != config_fingerprint():
            raise ValueError("Curated plan uses an obsolete model or policy configuration")
        if (
            not _latest(plan.version)
            or not plan.extraction_run
            or not plan.extraction_run.active
            or plan.extraction_run.state != "succeeded"
            or plan.version.source.disposition == "excluded"
        ):
            raise ValueError("A current, eligible source and curation plan are required")
        if settings.MODE == "production":
            event = (
                m.DecisionEvent.objects.filter(
                    decision__family=plan.family,
                    decision__field="publication",
                    decision__kind="inclusion",
                    decision__status="resolved",
                    value__source_version_id=str(plan.version_id),
                )
                .select_related("decision")
                .order_by("-created_at")
                .first()
            )
            if (
                plan.version.source.disposition != "included"
                or event is None
                or event.revision != event.decision.revision
                or event.value.get("treatment") != "include"
                or event.actor_id is None
            ):
                raise ValueError("Live private publication needs an explicit inclusion decision")
        units = {
            str(unit.id): unit
            for unit in m.ExtractedUnit.objects.filter(extraction_run=plan.extraction_run)
        }
        for unit_id in plan.eligible_units:
            unit = units.get(unit_id)
            if unit is None:
                raise ValueError("Plan references a missing current extracted unit")
            event = _treatment_event(plan, unit_id)
            specs.append((unit, event, "excerpt", [unit_id], unit.text.encode("utf-8")))
        for summary in plan.derived_summaries:
            source_ids = summary["source_units"]
            if not source_ids or any(unit_id not in units for unit_id in source_ids):
                raise ValueError("Derived summary has invalid source mapping")
            if not summary_support_current(plan, summary):
                raise ValueError("Derived summary has withdrawn supporting evidence")
            event = m.DecisionEvent.objects.filter(
                pk=summary["decision_event_id"], decision__family=plan.family
            ).first()
            if (
                event is None
                or plan.decision_revisions.get(str(event.decision_id)) != event.revision
                or event.decision.revision != event.revision
            ):
                raise ValueError("Derived summary decision is stale")
            specs.append(
                (
                    units[source_ids[0]],
                    event,
                    "summary",
                    source_ids,
                    summary["text"].encode("utf-8"),
                )
            )
    return plans, specs


def _fingerprint(plans, specs):
    return hashlib.sha256(
        _json_bytes(
            [(str(plan.id), plan.fingerprint) for plan in plans]
            + [
                (str(unit.id), str(event.id), kind, source_ids, hashlib.sha256(raw).hexdigest())
                for unit, event, kind, source_ids, raw in specs
            ]
        )
    ).hexdigest()


@transaction.atomic
def stage(user, proposal_id):
    """Create immutable curated bytes without withdrawing the previous active generation."""
    proposal = m.Proposal.objects.select_for_update().filter(pk=proposal_id).first()
    if proposal is None:
        raise Http404
    services.authorize(user, proposal.collection_id)
    if settings.APP["publication_hold"]:
        raise ValueError("Publication is held pending recovery reconciliation")
    plans, specs = _plan_specs(proposal)
    if not plans or not specs:
        raise ValueError("No current plan has publishable eligible excerpts")
    fingerprint = _fingerprint(plans, specs)
    existing = (
        m.PublicationGeneration.objects.filter(proposal=proposal, fingerprint=fingerprint)
        .exclude(state__in=["failed", "retired"])
        .order_by("-revision")
        .first()
    )
    if existing:
        return existing
    revision = (
        m.PublicationGeneration.objects.filter(proposal=proposal).aggregate(Max("revision"))[
            "revision__max"
        ]
        or 0
    ) + 1
    backend = settings.APP["publication_backend"]
    if backend not in {"local", "managed_kb"}:
        raise ValueError("Unknown publication backend")
    if settings.MODE == "production" and backend != "managed_kb":
        raise ValueError("Production publication requires the Managed KB backend")
    generation = m.PublicationGeneration.objects.create(
        proposal=proposal,
        revision=revision,
        fingerprint=fingerprint,
        backend=backend,
        expected_count=len(specs),
    )
    storage = LocalObjectStorage(
        settings.LOCAL_STORAGE_ROOT, require_durable=settings.MODE == "production"
    )
    seen = set()
    for unit, event, kind, source_ids, raw in specs:
        if unit.id in seen:
            raise ValueError(
                "A generation cannot contain overlapping excerpt and summary artifacts"
            )
        seen.add(unit.id)
        if not raw or len(raw) > settings.APP["publication_max_artifact_bytes"]:
            raise ValueError("Curated artifact is empty or too large")
        digest = hashlib.sha256(raw).hexdigest()
        key = storage.put_immutable(digest, raw)
        blob, _ = m.ContentBlob.objects.get_or_create(
            sha256=digest, defaults={"size": len(raw), "storage_key": key}
        )
        if blob.size != len(raw) or blob.storage_key != key:
            raise ValueError("Curated blob identity mismatch")
        artifact = m.PublicationArtifact.objects.create(
            generation=generation,
            unit=unit,
            decision_event=event,
            blob=blob,
            eligible=True,
            kind=kind,
            source_unit_ids=source_ids,
            locator=unit.locator,
        )
        artifact.object_key = (
            f"{settings.APP['publication_s3_prefix'].rstrip('/')}/"
            f"{generation.id}/{artifact.id}.txt"
        )
        artifact.metadata = metadata_for(artifact)
        artifact.save(update_fields=["object_key", "metadata"])
    return generation


class ManagedKBAdapter:
    """Thin AWS request adapter; the application owns mapping and eligibility."""

    def __init__(self, *, s3=None, control=None, runtime=None):
        import boto3

        region = os.environ.get("AWS_REGION")
        self.bucket = os.environ.get("PROPOSAL_CURATED_BUCKET")
        self.kb_id = os.environ.get("BEDROCK_KNOWLEDGE_BASE_ID")
        self.data_source_id = os.environ.get("BEDROCK_DATA_SOURCE_ID")
        if not all((region, self.bucket, self.kb_id, self.data_source_id)):
            raise ValueError("Managed KB publication settings are incomplete")
        self.s3 = s3 or boto3.client("s3", region_name=region)
        self.control = control or boto3.client("bedrock-agent", region_name=region)
        self.runtime = runtime or boto3.client("bedrock-agent-runtime", region_name=region)

    def uri(self, artifact):
        return f"s3://{self.bucket}/{artifact.object_key}"

    def verify_scope(self):
        source = self.control.get_data_source(
            knowledgeBaseId=self.kb_id, dataSourceId=self.data_source_id
        )["dataSource"]
        configuration = source.get("dataSourceConfiguration", {})
        s3 = configuration.get("s3Configuration", {})
        if (
            source.get("status") != "AVAILABLE"
            or configuration.get("type") != "S3"
            or s3.get("bucketArn") != f"arn:aws:s3:::{self.bucket}"
            or s3.get("inclusionPrefixes") != [settings.APP["publication_s3_prefix"]]
        ):
            raise ValueError("Managed KB source must ingest only the curated bucket prefix")

    def upload(self, artifact, raw):
        self.s3.put_object(
            Bucket=self.bucket,
            Key=artifact.object_key,
            Body=raw,
            ServerSideEncryption="AES256",
            ContentType="text/plain; charset=utf-8",
        )
        self.s3.put_object(
            Bucket=self.bucket,
            Key=artifact.object_key + ".metadata.json",
            Body=_json_bytes(artifact.metadata),
            ServerSideEncryption="AES256",
            ContentType="application/json",
        )

    def start(self, generation, *, operation="publish"):
        previous = (
            generation.deletion_job_id if operation == "delete" else generation.ingestion_job_id
        )
        return self.control.start_ingestion_job(
            knowledgeBaseId=self.kb_id,
            dataSourceId=self.data_source_id,
            clientToken=hashlib.sha256(
                f"{generation.id}:{operation}:{previous}".encode()
            ).hexdigest(),
            description=f"proposal-generation-{generation.id}",
        )["ingestionJob"]["ingestionJobId"]

    def job(self, job_id):
        return self.control.get_ingestion_job(
            knowledgeBaseId=self.kb_id,
            dataSourceId=self.data_source_id,
            ingestionJobId=job_id,
        )["ingestionJob"]

    def statuses(self, artifacts):
        statuses = {}
        for offset in range(0, len(artifacts), 10):
            batch = artifacts[offset : offset + 10]
            response = self.control.get_knowledge_base_documents(
                knowledgeBaseId=self.kb_id,
                dataSourceId=self.data_source_id,
                documentIdentifiers=[
                    {"dataSourceType": "S3", "s3": {"uri": self.uri(item)}} for item in batch
                ],
            )
            for detail in response.get("documentDetails", []):
                uri = detail.get("identifier", {}).get("s3", {}).get("uri")
                if uri:
                    statuses[uri] = detail.get("status")
        return statuses

    def retrieve(self, query):
        return self.runtime.retrieve(
            knowledgeBaseId=self.kb_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "managedSearchConfiguration": {
                    "numberOfResults": settings.APP["publication_retrieve_limit"]
                }
            },
        ).get("retrievalResults", [])

    def delete(self, artifact):
        for key in (artifact.object_key, artifact.object_key + ".metadata.json"):
            self.s3.delete_object(Bucket=self.bucket, Key=key)


def _still_current(generation):
    """All staged excerpts must still be authorized at the activation boundary."""
    try:
        plans, specs = _plan_specs(generation.proposal)
    except ValueError:
        return False
    expected = {(str(unit.id), str(event.id), kind) for unit, event, kind, _, _ in specs}
    actual = {
        (str(item.unit_id), str(item.decision_event_id), item.kind)
        for item in m.PublicationArtifact.objects.filter(generation=generation, eligible=True)
    }
    return (
        expected == actual
        and len(actual) == generation.expected_count
        and generation.fingerprint == _fingerprint(plans, specs)
    )


@transaction.atomic
def _activate(generation_id):
    generation = m.PublicationGeneration.objects.select_related("proposal").get(pk=generation_id)
    m.Proposal.objects.select_for_update().get(pk=generation.proposal_id)
    # Curation writers lock families; source reconciliation invalidates plans.
    # Hold both locks through the final eligibility check and state swap.
    list(
        m.VersionFamily.objects.select_for_update()
        .filter(proposal_id=generation.proposal_id)
        .order_by("id")
        .values_list("id", flat=True)
    )
    list(
        m.CurationPlan.objects.select_for_update()
        .filter(family__proposal_id=generation.proposal_id, state="current")
        .order_by("id")
        .values_list("id", flat=True)
    )
    if settings.APP["publication_hold"]:
        raise ValueError("Publication is held pending recovery reconciliation")
    if not _still_current(generation):
        generation.state, generation.failure = "failed", "eligibility_changed"
        generation.save(update_fields=["state", "failure"])
        return generation
    if generation.state == "active":
        return generation
    if generation.state != "verified":
        raise ValueError("Only a verified generation can activate")
    m.PublicationGeneration.objects.filter(proposal=generation.proposal, state="active").update(
        state="retired"
    )
    generation.state = "active"
    generation.save(update_fields=["state"])
    m.AuditRecord.objects.create(
        action="publication.activated",
        object_id=generation.id,
        details={"revision": generation.revision, "artifact_count": generation.expected_count},
    )
    return generation


def _reconciliation_expired(generation):
    started = generation.indexing_started_at or generation.created_at
    return (timezone.now() - started).total_seconds() > settings.APP[
        "publication_reconcile_timeout_seconds"
    ]


def process(generation_id, adapter=None):
    """Idempotent upload/start/observe step; safe to call after a worker crash."""
    generation = m.PublicationGeneration.objects.select_related("proposal").get(pk=generation_id)
    if generation.state == "active":
        return generation
    if generation.state == "failed":
        generation.state, generation.failure = "staged", ""
        generation.save(update_fields=["state", "failure"])
    if not _still_current(generation):
        generation.state, generation.failure = "failed", "eligibility_changed"
        generation.save(update_fields=["state", "failure"])
        return generation
    artifacts = list(
        m.PublicationArtifact.objects.filter(generation=generation)
        .select_related("blob", "unit")
        .order_by("id")
    )
    storage = LocalObjectStorage(settings.LOCAL_STORAGE_ROOT)
    if generation.backend == "local":
        for artifact in artifacts:
            raw = storage.get(artifact.blob.storage_key)
            if hashlib.sha256(raw).hexdigest() != artifact.blob.sha256:
                raise ValueError("Curated byte verification failed")
            artifact.index_state = "indexed"
            artifact.save(update_fields=["index_state"])
        generation.state, generation.verified_at = "verified", timezone.now()
        generation.save(update_fields=["state", "verified_at"])
        return generation if settings.APP["publication_hold"] else _activate(generation.id)
    if adapter is None:
        try:
            adapter = ManagedKBAdapter()
        except Exception:
            generation.state, generation.failure = "failed", "adapter_unavailable"
            generation.save(update_fields=["state", "failure"])
            return generation
    if generation.state == "staged":
        try:
            adapter.verify_scope()
        except Exception:
            generation.state, generation.failure = "failed", "scope_unverified"
            generation.save(update_fields=["state", "failure"])
            return generation
        try:
            for artifact in artifacts:
                adapter.upload(artifact, storage.get(artifact.blob.storage_key))
                artifact.index_state = "uploaded"
                artifact.save(update_fields=["index_state"])
        except Exception:
            generation.state, generation.failure = "failed", "upload_failed"
            generation.save(update_fields=["state", "failure"])
            return generation
        generation.state = "uploaded"
        generation.save(update_fields=["state"])
    if generation.state == "uploaded":
        try:
            adapter.verify_scope()
        except Exception:
            generation.state, generation.failure = "failed", "scope_unverified"
            generation.save(update_fields=["state", "failure"])
            return generation
        try:
            generation.ingestion_job_id = adapter.start(generation)
        except Exception as exc:
            response = getattr(exc, "response", {})
            error = response.get("Error", {}) if isinstance(response, dict) else {}
            code = error.get("Code") if isinstance(error, dict) else None
            if code in {
                "ConflictException",
                "ThrottlingException",
                "ServiceQuotaExceededException",
            }:
                generation.failure = "ingestion_start_deferred"
                generation.save(update_fields=["failure"])
                return generation
            generation.state, generation.failure = "failed", "ingestion_start_failed"
            generation.save(update_fields=["state", "failure"])
            return generation
        generation.state, generation.indexing_started_at, generation.failure = (
            "indexing",
            timezone.now(),
            "",
        )
        generation.save(
            update_fields=["ingestion_job_id", "state", "indexing_started_at", "failure"]
        )
    if generation.state == "indexing":
        try:
            job = adapter.job(generation.ingestion_job_id)
        except Exception:
            expired = _reconciliation_expired(generation)
            generation.failure = (
                "ingestion_observation_timeout" if expired else "ingestion_observation_failed"
            )
            if expired:
                generation.state = "failed"
            generation.save(update_fields=["state", "failure"])
            return generation
        if job["status"] in {"FAILED", "STOPPED"}:
            generation.state, generation.failure = "failed", "ingestion_failed"
            generation.save(update_fields=["state", "failure"])
            return generation
        if job["status"] != "COMPLETE":
            if _reconciliation_expired(generation):
                generation.state, generation.failure = "failed", "ingestion_timeout"
                generation.save(update_fields=["state", "failure"])
            return generation
        try:
            statuses = adapter.statuses(artifacts)
        except Exception:
            expired = _reconciliation_expired(generation)
            generation.failure = (
                "document_observation_timeout" if expired else "document_observation_failed"
            )
            if expired:
                generation.state = "failed"
            generation.save(update_fields=["state", "failure"])
            return generation
        complete = True
        terminal_failure = False
        for artifact in artifacts:
            status = statuses.get(adapter.uri(artifact), "NOT_FOUND")
            artifact.index_state = status.lower()
            artifact.save(update_fields=["index_state"])
            complete &= status == "INDEXED"
            terminal_failure |= status in {
                "FAILED",
                "PARTIALLY_INDEXED",
                "METADATA_PARTIALLY_INDEXED",
                "METADATA_UPDATE_FAILED",
                "IGNORED",
            }
        if not complete:
            if terminal_failure or _reconciliation_expired(generation):
                generation.state, generation.failure = "failed", "documents_not_indexed"
                generation.save(update_fields=["state", "failure"])
            return generation
        generation.state, generation.verified_at, generation.failure = (
            "verified",
            timezone.now(),
            "",
        )
        generation.save(update_fields=["state", "verified_at", "failure"])
    if generation.state == "verified":
        return generation if settings.APP["publication_hold"] else _activate(generation.id)
    return generation


def retrieve(user, collection_id, query, adapter=None):
    """Discard every provider byte until its exact active application mapping is checked."""
    services.authorize(user, collection_id)
    if not query.strip():
        return []
    if settings.APP["publication_hold"]:
        return []
    active = set(
        m.PublicationGeneration.objects.filter(
            proposal__collection_id=collection_id, state="active"
        ).values_list("id", flat=True)
    )
    adapter = adapter or ManagedKBAdapter()
    candidates = adapter.retrieve(query[:500])
    ids = []
    for item in candidates:
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            continue
        try:
            ids.append(uuid.UUID(str(metadata.get("artifact_id"))))
        except (TypeError, ValueError, AttributeError):
            continue
    allowed = {
        str(item.id): item
        for item in services.factual_artifacts(user, collection_id, ids).select_related(
            "unit__version__source", "generation", "blob"
        )
    }
    selected = {}
    for item in candidates:
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            continue
        artifact_id = metadata.get("artifact_id")
        if not isinstance(artifact_id, str):
            continue
        artifact = allowed.get(artifact_id)
        location = item.get("location")
        s3_location = location.get("s3Location") if isinstance(location, dict) else None
        if (
            artifact is None
            or artifact.generation_id not in active
            or metadata.get("generation_id") != str(artifact.generation_id)
            or metadata.get("content_sha256") != artifact.blob.sha256
            or not isinstance(s3_location, dict)
            or s3_location.get("uri") != adapter.uri(artifact)
        ):
            continue
        score = item.get("score", 0)
        if not isinstance(score, (int, float)) or not math.isfinite(score):
            score = 0
        previous = selected.get(artifact_id)
        if previous is None or score > previous[0]:
            selected[artifact_id] = (score, artifact)
    results = []
    for score, artifact in sorted(selected.values(), key=lambda pair: -pair[0]):
        results.append(
            {
                "artifact_id": str(artifact.id),
                "generation_id": str(artifact.generation_id),
                "text": LocalObjectStorage(settings.LOCAL_STORAGE_ROOT)
                .get(artifact.blob.storage_key)
                .decode("utf-8"),
                "locator": artifact.locator,
                "source_version_id": str(artifact.unit.version_id),
                "source_unit_ids": artifact.source_unit_ids,
                "title": artifact.unit.version.source.display_path.rsplit("/", 1)[-1],
                "locator_label": ", ".join(
                    f"{key} {value}" for key, value in artifact.locator.items()
                ),
                "source_url": f"/artifacts/{artifact.id}/",
                "support_kind": "factual",
                "score": score,
            }
        )
    return results


def validate_packet(user, collection_id, packet):
    """Saved packets are historical until every cited artifact is reauthorized."""
    try:
        ids = [uuid.UUID(str(item["artifact_id"])) for item in packet]
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
    allowed = {
        str(artifact.id): artifact
        for artifact in services.factual_artifacts(user, collection_id, ids)
    }
    return all(
        item.get("artifact_id") in allowed
        and item.get("generation_id") == str(allowed[item["artifact_id"]].generation_id)
        and item.get("source_version_id") == str(allowed[item["artifact_id"]].unit.version_id)
        for item in packet
    )


def cleanup_retired(generation_id, adapter=None):
    """Delete retired S3 bytes, sync, and verify exact absence; retrieval stays gated."""
    generation = m.PublicationGeneration.objects.get(pk=generation_id)
    if generation.state != "retired" or generation.backend != "managed_kb":
        raise ValueError("Only retired Managed KB generations may be cleaned up")
    if generation.deletion_state == "complete":
        return generation
    adapter = adapter or ManagedKBAdapter()
    adapter.verify_scope()
    with transaction.atomic():
        m.Proposal.objects.select_for_update().get(pk=generation.proposal_id)
        generation = m.PublicationGeneration.objects.select_for_update().get(pk=generation_id)
        if generation.state != "retired":
            raise ValueError("Only retired Managed KB generations may be cleaned up")
        deleting = not generation.deletion_job_id or generation.deletion_state == "failed"
        if deleting:
            # Persist the marker before any external deletion so restore cannot
            # activate stale index entries after S3 bytes are gone.
            generation.deletion_state = "deleting"
            generation.save(update_fields=["deletion_state"])
    artifacts = list(m.PublicationArtifact.objects.filter(generation=generation).order_by("id"))
    if deleting:
        for artifact in artifacts:
            adapter.delete(artifact)
        generation.deletion_job_id = adapter.start(generation, operation="delete")
        generation.deletion_state = "indexing"
        generation.save(update_fields=["deletion_job_id", "deletion_state"])
    job = adapter.job(generation.deletion_job_id)
    if job["status"] in {"FAILED", "STOPPED"}:
        generation.deletion_state = "failed"
    elif job["status"] == "COMPLETE":
        statuses = adapter.statuses(artifacts)
        generation.deletion_state = (
            "complete"
            if all(
                statuses.get(adapter.uri(item), "NOT_FOUND") == "NOT_FOUND" for item in artifacts
            )
            else "pending"
        )
    generation.save(update_fields=["deletion_state"])
    return generation


@transaction.atomic
def restore_verified(generation_id, adapter=None):
    """Rollback only when the old generation is still eligible and exactly indexed."""
    proposal_id = m.PublicationGeneration.objects.values_list("proposal_id", flat=True).get(
        pk=generation_id
    )
    m.Proposal.objects.select_for_update().get(pk=proposal_id)
    generation = m.PublicationGeneration.objects.select_for_update().get(pk=generation_id)
    if generation.state != "retired" or settings.APP["publication_hold"]:
        raise ValueError("Generation is not available for verified restore")
    if generation.deletion_job_id or generation.deletion_state:
        raise ValueError("Retired generation cleanup has started; restore is unsafe")
    if not _still_current(generation):
        raise ValueError("Retired generation no longer matches current decisions")
    artifacts = list(m.PublicationArtifact.objects.filter(generation=generation))
    if generation.backend == "managed_kb":
        adapter = adapter or ManagedKBAdapter()
        adapter.verify_scope()
        statuses = adapter.statuses(artifacts)
        if any(statuses.get(adapter.uri(item)) != "INDEXED" for item in artifacts):
            raise ValueError("Retired generation is not exactly indexed")
    else:
        storage = LocalObjectStorage(settings.LOCAL_STORAGE_ROOT)
        for artifact in artifacts:
            storage.get(artifact.blob.storage_key)
    generation.state = "verified"
    generation.save(update_fields=["state"])
    return _activate(generation.id)


def reconcile_once():
    """One bounded worker poll; incomplete ingestion waits for the next poll."""
    if settings.APP["publication_hold"]:
        return False
    generations = list(
        m.PublicationGeneration.objects.filter(
            state__in=["staged", "uploaded", "indexing", "verified"]
        ).order_by("created_at")[:20]
    )
    changed = False
    for generation in generations:
        previous = generation.state
        try:
            current = process(generation.id)
        except Exception:
            m.PublicationGeneration.objects.filter(pk=generation.id).update(
                state="failed", failure="reconcile_error"
            )
            changed = True
            continue
        changed |= current.state != previous
    return changed
