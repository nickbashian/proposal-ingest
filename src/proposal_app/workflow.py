"""MVP-02 local workflow built on the durable application domain."""

import hashlib
import re
from pathlib import Path
from urllib.parse import urljoin

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.http import Http404
from django.urls import reverse

from . import models as m, services
from .adapters import DeterministicDraftingAdapter, LocalRetrievalAdapter
from .curation import DIMENSIONS
from .storage import LocalObjectStorage

LOCAL_RETRIEVAL_LABEL = "Local deterministic retrieval"
LOCAL_DRAFTING_LABEL = "Deterministic local drafting"
FIXTURE_JOB_KIND = "fixture-slice"


def enqueue_fixture_import(user, collection_id):
    if settings.MODE != "local":
        raise ValueError("Synthetic fixture import is local only")
    return services.create_job(
        user,
        collection_id,
        f"fixture-slice:{settings.APP['fixture_slice_revision']}",
        kind=FIXTURE_JOB_KIND,
        payload={"fixture_revision": settings.APP["fixture_slice_revision"]},
    )


def _validate_fixture(result: dict) -> None:
    if not isinstance(result, dict) or not all(
        isinstance(result.get(key), str) for key in ("revision", "proposal", "family")
    ):
        raise ValueError("Fixture result is incomplete")
    if result.get("revision") != settings.APP["fixture_slice_revision"]:
        raise ValueError("Fixture revision does not match application configuration")
    items = result.get("items")
    if result.get("synthetic") is not True or not isinstance(items, list) or not items:
        raise ValueError("Fixture result is incomplete")
    for item in items:
        if (
            not isinstance(item, dict)
            or item.get("initial_disposition") not in {"awaiting_decision", "included", "excluded"}
            or item.get("support_kind") not in {"factual", "voice"}
            or not isinstance(item.get("locator"), dict)
            or not all(
                isinstance(item.get(key), str)
                for key in ("key", "title", "display_path", "text", "reason")
            )
        ):
            raise ValueError("Fixture item violates the local workflow contract")


@transaction.atomic
def deliver_fixture_import(job: m.Job) -> dict:
    """Persist a worker result idempotently through the production domain models."""

    if job.kind != FIXTURE_JOB_KIND:
        raise ValueError("Job is not a fixture-slice import")
    if settings.MODE != "local":
        raise ValueError("Synthetic fixture delivery is local only")
    services.authorize(job.creator, job.collection_id)
    result = job.result
    _validate_fixture(result)
    proposal = None
    sources = []
    for item in result["items"]:
        content = f"{item['title']}\n\n{item['text']}\n".encode("utf-8")
        version = services.observe_source(
            job.creator,
            job.collection_id,
            identity={
                "connector": "local-fixture",
                "tenant": f"collection-{job.collection_id}",
                "site": result["proposal"],
                "drive": result["family"],
                "item": item["key"],
            },
            path=item["display_path"],
            observation_key=result["revision"],
            content=content,
            proposal=result["proposal"],
            family=result["family"],
            upstream_version=result["revision"],
        )
        source = version.source
        family = m.VersionFamily.objects.get(
            proposalmembership__source=source,
            proposal__collection_id=job.collection_id,
            proposal__identifier=result["proposal"],
            key=result["family"],
        )
        proposal = family.proposal
        unit, created = m.ExtractedUnit.objects.get_or_create(
            version=version,
            extractor_revision="synthetic-structured-v1",
            key=item["key"],
            defaults={
                "locator": item["locator"],
                "text": item["text"],
                "support_kind": item["support_kind"],
            },
        )
        if not created and (
            unit.locator != item["locator"]
            or unit.text != item["text"]
            or unit.support_kind != item["support_kind"]
        ):
            raise ValueError("Fixture unit identity cannot be rewritten")
        decision, _ = m.Decision.objects.get_or_create(
            family=family,
            scope=f"version:{version.id}",
            field="publication",
            kind="inclusion",
        )
        if decision.revision == 0:
            source.disposition = item["initial_disposition"]
            source.disposition_reason = item["reason"]
            source.save(update_fields=["disposition", "disposition_reason"])
            if item["initial_disposition"] != "awaiting_decision":
                treatment = "include" if item["initial_disposition"] == "included" else "exclude"
                services.append_decision(
                    job.creator,
                    decision.id,
                    0,
                    value={
                        "treatment": treatment,
                        "support_kind": item["support_kind"],
                        "fixture_default": True,
                    },
                    rationale=item["reason"],
                    evidence=[str(unit.id)],
                )
        sources.append(str(source.id))
    if proposal is None:
        raise ValueError("Fixture contains no proposal")
    return {
        "proposal_id": str(proposal.id),
        "source_ids": sources,
        "source_count": len(sources),
        "fixture_revision": result["revision"],
    }


@transaction.atomic
def answer_inclusion(user, decision_id, expected_revision: int, treatment: str):
    if treatment not in {"include", "exclude"}:
        raise ValueError("Choose include or exclude")
    decision = (
        m.Decision.objects.select_for_update()
        .select_related("family__proposal")
        .filter(pk=decision_id, field="publication", kind="inclusion")
        .first()
    )
    if decision is None:
        raise Http404
    services.authorize(user, decision.family.proposal.collection_id)
    m.Proposal.objects.select_for_update().get(pk=decision.family.proposal_id)
    prefix = "version:"
    if not decision.scope.startswith(prefix):
        raise ValueError("Decision scope is not supported")
    version = (
        m.SourceVersion.objects.select_related("source")
        .filter(pk=decision.scope.removeprefix(prefix))
        .first()
    )
    if (
        version is None
        or not m.ProposalMembership.objects.filter(
            source=version.source, family=decision.family
        ).exists()
    ):
        raise ValueError("Decision version no longer matches its family")
    previous = m.DecisionEvent.objects.filter(decision=decision).order_by("-revision").first()
    if previous and previous.value.get("fixture_default"):
        raise ValueError("Fixture policy decisions are not editable")
    active_run = m.ExtractionRun.objects.filter(version=version, active=True).first()
    reviewed_units = list(
        m.ExtractedUnit.objects.filter(version=version, extraction_run=active_run).order_by("key")
    )
    if not reviewed_units or any(unit.support_kind != "factual" for unit in reviewed_units):
        raise ValueError("This review action requires factual passages from one source version")
    source = version.source
    event = services.append_decision(
        user,
        decision.id,
        expected_revision,
        value={
            "treatment": treatment,
            "support_kind": "factual",
            "source_version_id": str(version.id),
        },
        rationale="Explicit MVP-02 inclusion review",
        evidence=[str(unit.id) for unit in reviewed_units],
    )
    m.PublicationArtifact.objects.filter(
        generation__proposal=decision.family.proposal,
        generation__state="active",
        unit__version__source=source,
        eligible=True,
    ).update(eligible=False)
    source.disposition = "included" if treatment == "include" else "excluded"
    source.disposition_reason = "Recorded by the authenticated reviewer."
    source.save(update_fields=["disposition", "disposition_reason"])
    return event


def _store_curated_bytes(content: bytes) -> m.ContentBlob:
    digest = hashlib.sha256(content).hexdigest()
    key = LocalObjectStorage(
        settings.LOCAL_STORAGE_ROOT, require_durable=settings.MODE == "production"
    ).put_immutable(digest, content)
    blob, _ = m.ContentBlob.objects.get_or_create(
        sha256=digest, defaults={"size": len(content), "storage_key": key}
    )
    if blob.size != len(content):
        raise ValueError("Stored content metadata does not match curated bytes")
    if not blob.storage_key:
        blob.storage_key = key
        blob.save(update_fields=["storage_key"])
    return blob


@transaction.atomic
def publish(user, proposal_id) -> m.PublicationGeneration:
    proposal = m.Proposal.objects.select_for_update().filter(pk=proposal_id).first()
    if proposal is None:
        raise Http404
    services.authorize(user, proposal.collection_id)
    sources = m.SourceItem.objects.filter(proposalmembership__family__proposal=proposal).distinct()
    if sources.filter(disposition="awaiting_decision").exists():
        raise ValueError("Answer all inclusion decisions before publication")
    specifications = []
    for source in sources.filter(disposition="included").order_by("id"):
        family = m.VersionFamily.objects.select_for_update().get(
            proposal=proposal, proposalmembership__source=source
        )
        version_scopes = [
            f"version:{version_id}"
            for version_id in m.SourceVersion.objects.filter(source=source).values_list(
                "id", flat=True
            )
        ]
        event = (
            m.DecisionEvent.objects.filter(
                decision__family=family,
                decision__scope__in=version_scopes,
                decision__field="publication",
                decision__kind="inclusion",
            )
            .select_related("decision")
            .order_by("-created_at")
            .first()
        )
        if event is None or event.value.get("treatment") != "include":
            raise ValueError("Included source lacks a current inclusion event")
        if not event.decision.scope.startswith("version:"):
            raise ValueError("Inclusion event is not bound to a source version")
        approved_version_id = event.value.get(
            "source_version_id", event.decision.scope.removeprefix("version:")
        )
        approved_unit_ids = [str(unit_id) for unit_id in event.evidence]
        units = m.ExtractedUnit.objects.filter(
            version_id=approved_version_id,
            version__source=source,
            id__in=approved_unit_ids,
        ).order_by("key")
        if not units.exists():
            raise ValueError("Inclusion event covers no extracted passage")
        active_run = m.ExtractionRun.objects.filter(
            version_id=approved_version_id, active=True
        ).first()
        if active_run and units.exclude(extraction_run=active_run).exists():
            raise ValueError("Inclusion event needs review against the active extraction")
        has_curation = (
            m.Decision.objects.filter(
                family=family, field__in=DIMENSIONS | {"voice_approval"}
            ).exists()
            or m.ClassificationFact.objects.filter(family=family).exists()
            or m.CurationPlan.objects.filter(family=family, version_id=approved_version_id).exists()
        )
        if has_curation:
            plan = m.CurationPlan.objects.filter(
                family=family,
                version_id=approved_version_id,
                state="current",
                extraction_run=active_run,
            ).first()
            if plan is None:
                raise ValueError("Curated plan needs review against the active extraction")
            units = units.filter(id__in=plan.eligible_units)
        for unit in units:
            specifications.append((unit, event))
    if not specifications:
        raise ValueError("No eligible passages are available to publish")
    active = (
        m.PublicationGeneration.objects.select_for_update()
        .filter(proposal=proposal, state="active")
        .first()
    )
    desired = {(unit.id, event.id) for unit, event in specifications}
    if active is not None:
        existing = set(
            m.PublicationArtifact.objects.filter(generation=active, eligible=True).values_list(
                "unit_id", "decision_event_id"
            )
        )
        if existing == desired:
            return active
        active.state = "retired"
        active.save(update_fields=["state"])
    revision = (
        m.PublicationGeneration.objects.filter(proposal=proposal).aggregate(Max("revision"))[
            "revision__max"
        ]
        or 0
    ) + 1
    generation = m.PublicationGeneration.objects.create(
        proposal=proposal, revision=revision, state="staged"
    )
    for unit, event in specifications:
        blob = _store_curated_bytes(unit.text.encode("utf-8"))
        m.PublicationArtifact.objects.create(
            generation=generation,
            unit=unit,
            decision_event=event,
            blob=blob,
            eligible=True,
        )
    generation.state = "active"
    generation.save(update_fields=["state"])
    m.AuditRecord.objects.create(
        actor=user,
        action="publication.activated",
        object_id=generation.id,
        details={"revision": generation.revision, "artifact_count": len(specifications)},
    )
    return generation


def locator_label(locator: dict) -> str:
    preferred = ["page", "slide", "section", "paragraph", "table", "cell"]
    keys = [key for key in preferred if key in locator]
    keys.extend(sorted(set(locator) - set(keys)))
    return ", ".join(f"{key} {locator[key]}" for key in keys)


def search(user, collection_id, query: str) -> list[dict]:
    services.authorize(user, collection_id)
    if not query.strip():
        return []
    artifacts = services.eligible_artifacts(
        user,
        collection_id,
        m.PublicationArtifact.objects.filter(
            generation__proposal__collection_id=collection_id,
            generation__state="active",
            eligible=True,
            unit__support_kind="factual",
        ).values_list("id", flat=True),
    ).select_related("generation", "unit__version__source")
    candidates = []
    generations = []
    for artifact in artifacts:
        generations.append(str(artifact.generation_id))
        candidates.append(
            {
                "artifact_id": str(artifact.id),
                "generation_id": str(artifact.generation_id),
                "title": Path(artifact.unit.version.source.display_path).name,
                "text": artifact.unit.text,
                "locator": artifact.unit.locator,
                "locator_label": locator_label(artifact.unit.locator),
                "source_url": reverse("artifact", args=[artifact.id]),
                "support_kind": artifact.unit.support_kind,
            }
        )
    return LocalRetrievalAdapter(candidates).retrieve(query[:500], generations)


@transaction.atomic
def pin_evidence(user, session_id, artifact_id) -> m.EvidencePin:
    session = services.owned(user, m.DraftSession, session_id)
    session = m.DraftSession.objects.select_for_update().get(pk=session.id)
    if session.deleted_at:
        raise Http404
    artifact = (
        services.eligible_artifacts(user, session.collection_id, [artifact_id])
        .select_related("unit")
        .filter(unit__support_kind="factual")
        .first()
    )
    if artifact is None:
        raise Http404
    pin, created = m.EvidencePin.objects.get_or_create(
        session=session, artifact=artifact, defaults={"actor": user}
    )
    if created:
        m.AuditRecord.objects.create(actor=user, action="evidence.pinned", object_id=pin.id)
    return pin


@transaction.atomic
def generate(user, session_id, prompt: str) -> m.DraftRevision:
    session = services.owned(user, m.DraftSession, session_id)
    session = m.DraftSession.objects.select_for_update().get(pk=session.id)
    if session.deleted_at:
        raise Http404
    pins = list(
        m.EvidencePin.objects.filter(session=session).select_related(
            "artifact__unit__version__source", "artifact__generation"
        )
    )
    eligible = {
        artifact.id: artifact
        for artifact in services.eligible_artifacts(
            user, session.collection_id, [pin.artifact_id for pin in pins]
        ).filter(unit__support_kind="factual")
    }
    evidence = []
    for pin in pins:
        artifact = eligible.get(pin.artifact_id)
        if artifact is None:
            continue
        unit = artifact.unit
        evidence.append(
            {
                "artifact_id": str(artifact.id),
                "source_version_id": str(unit.version_id),
                "unit_id": str(unit.id),
                "title": Path(unit.version.source.display_path).name,
                "text": unit.text,
                "locator": unit.locator,
                "locator_label": locator_label(unit.locator),
                "source_url": reverse("artifact", args=[artifact.id]),
                "support_kind": unit.support_kind,
            }
        )
    if not evidence:
        raise ValueError("Pin at least one currently eligible factual passage")
    latest = m.DraftRevision.objects.filter(session=session).order_by("-number").first()
    packet = m.EvidencePacket.objects.create(
        session=session, payload=evidence, policy_revision="local-evidence-v1"
    )
    result = DeterministicDraftingAdapter().draft(
        {
            "evidence": evidence,
            "base_text": latest.text if latest else "",
            "prior_evidence": latest.packet.payload if latest else [],
        },
        prompt,
        idempotency_key=f"{session.id}:{session.revision + 1}",
    )
    session.revision += 1
    session.save(update_fields=["revision"])
    revision = m.DraftRevision.objects.create(
        session=session,
        number=session.revision,
        packet=packet,
        text=result.value["text"],
        model_revision=DeterministicDraftingAdapter.revision,
        prompt_revision="local-writing-form-v1",
    )
    m.AuditRecord.objects.create(actor=user, action="draft.generated", object_id=revision.id)
    return revision


def edit(user, session_id, expected_revision: int, text: str) -> m.DraftRevision:
    session = services.owned(user, m.DraftSession, session_id)
    latest = m.DraftRevision.objects.filter(session=session).order_by("-number").first()
    if latest is None:
        raise ValueError("Generate a draft before editing")
    return services.revise_draft(
        user,
        session.id,
        expected_revision,
        text,
        packet_id=latest.packet_id,
    )


@transaction.atomic
def export(user, session_id, export_format: str, base_url: str) -> tuple[m.DraftExport, str, str]:
    if export_format not in {"markdown", "text"}:
        raise ValueError("Export format must be markdown or text")
    session = services.owned(user, m.DraftSession, session_id)
    session = m.DraftSession.objects.select_for_update().get(pk=session.id)
    if session.deleted_at:
        raise Http404
    revision = m.DraftRevision.objects.filter(session=session).order_by("-number").first()
    if revision is None:
        raise ValueError("Generate a draft before exporting")
    text = revision.text
    for marker in (
        DeterministicDraftingAdapter.evidence_start,
        DeterministicDraftingAdapter.evidence_end,
    ):
        text = text.replace(marker + "\n", "").replace(marker, "")

    def absolute_artifact_link(match: re.Match) -> str:
        label, destination = match.groups()
        if destination.startswith("/artifacts/"):
            destination = urljoin(base_url, destination)
        return f"[{label}]({destination})"

    text = re.sub(r"\[([^]]+)]\(([^)]+)\)", absolute_artifact_link, text)
    if export_format == "text":
        text = re.sub(r"\[([^]]+)]\(([^)]+)\)", r"\1: \2", text)
    exported = m.DraftExport.objects.create(revision=revision, text=text)
    extension = "md" if export_format == "markdown" else "txt"
    return exported, text, extension
