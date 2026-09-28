"""Current evidence browsing; historical passages never grant current eligibility."""

import hashlib
from pathlib import Path

from django.conf import settings
from django.db.models import Prefetch
from django.urls import reverse

from . import models as m, services, workflow
from .classification import _latest
from .curation import DIMENSIONS, config_fingerprint, effective_value


def labels(family, unit, *, decisions=None):
    result = {}
    events = {}
    for field in sorted(DIMENSIONS):
        try:
            value, event = effective_value(family, unit.version, unit, field, decisions=decisions)
        except ValueError:
            result[field] = "conflict"
            continue
        result[field] = (value or {}).get(
            "treatment" if field == "treatment" else "value", "unknown"
        )
        if event:
            events[str(event.decision_id)] = event.revision
    return result, events


def describe(unit, family, *, text=None, decisions=None):
    tags, decisions = labels(family, unit, decisions=decisions)
    return {
        "unit_id": str(unit.id),
        "source_id": str(unit.version.source_id),
        "source_version_id": str(unit.version_id),
        "source_version": unit.version.upstream_version or unit.version.observation_key,
        "date": unit.version.observed_at.isoformat(),
        "proposal": family.proposal.identifier,
        "family_id": str(family.id),
        "title": Path(unit.version.observed_path or unit.version.source.display_path).name,
        "text": unit.text if text is None else text,
        "original_text": unit.text,
        "locator": unit.locator,
        "locator_label": workflow.locator_label(unit.locator),
        "source_url": reverse("unit-inspector", args=[unit.id]),
        "labels": tags,
        "decision_revisions": decisions,
        "qualifications": unit.warnings,
        "context": unit.context,
    }


def factual_item(artifact, *, text=None, decisions=None):
    row = describe(
        artifact.unit,
        artifact.decision_event.decision.family,
        text=workflow.artifact_text(artifact) if text is None else text,
        decisions=decisions,
    )
    row.update(
        artifact_id=str(artifact.id),
        generation_id=str(artifact.generation_id),
        generation_revision=artifact.generation.revision,
        decision_event_id=str(artifact.decision_event_id),
        decision_revision=artifact.decision_event.revision,
        content_hash=artifact.blob.sha256,
        source_unit_ids=artifact.source_unit_ids or [str(artifact.unit_id)],
        locator=artifact.locator or artifact.unit.locator,
        locator_label=workflow.locator_label(artifact.locator or artifact.unit.locator),
        source_url=reverse("artifact", args=[artifact.id]),
        support_kind="factual",
    )
    return row


def voice_items(user, collection_id):
    services.authorize(user, collection_id)
    if settings.APP["publication_hold"]:
        return []
    rows = []
    for plan in m.CurationPlan.objects.filter(
        family__proposal__collection_id=collection_id,
        state="current",
        config_fingerprint=config_fingerprint(),
        extraction_run__active=True,
    ).select_related("family__proposal", "version__source"):
        if not _latest(plan.version) or plan.version.source.disposition == "excluded":
            continue
        if any(
            not m.Decision.objects.filter(pk=key, revision=value).exists()
            for key, value in plan.decision_revisions.items()
        ):
            continue
        for unit in m.ExtractedUnit.objects.filter(
            id__in=plan.voice_units,
            version=plan.version,
            extraction_run=plan.extraction_run,
        ).select_related("version__source"):
            approval, event = effective_value(plan.family, plan.version, unit, "voice_approval")
            if approval != {"approved": True} or not event or not event.actor_id:
                continue
            row = describe(unit, plan.family)
            row.update(
                support_kind="voice",
                plan_id=str(plan.id),
                plan_fingerprint=plan.fingerprint,
                approval_event_id=str(event.id),
                content_hash=hashlib.sha256(unit.text.encode()).hexdigest(),
            )
            rows.append(row)
    return rows


def browse(user, collection_id, query="", *, view="evidence", filters=None, excluded=()):
    services.authorize(user, collection_id)
    filters = filters or {}
    if view not in {"evidence", "reasoning", "requirements", "voice"}:
        raise ValueError("Unknown evidence view")
    exact = m.Proposal.objects.filter(collection_id=collection_id, identifier=query.strip()).first()
    artifacts = m.PublicationArtifact.objects.filter(
        generation__proposal__collection_id=collection_id,
        generation__state="active",
        eligible=True,
    ).select_related(
        "unit__version__source", "decision_event__decision__family__proposal", "generation", "blob"
    )
    terms = query.casefold().split()
    semantic = (
        settings.APP["publication_backend"] == "managed_kb"
        and query
        and not exact
        and view != "voice"
    )
    if exact:
        artifacts = artifacts.filter(generation__proposal=exact)
    if filters.get("proposal"):
        artifacts = artifacts.filter(generation__proposal__identifier=filters["proposal"])
    if view == "voice":
        rows = voice_items(user, collection_id)
    else:
        # Semantic retrieval is application-mapped; IDs and unqueried browsing remain deterministic.
        if semantic:
            from .publication import retrieve

            hits = {row["artifact_id"]: row for row in retrieve(user, collection_id, query)}
            artifacts = artifacts.filter(id__in=hits)
        candidates = []
        decisions = {}
        required_tags = {
            key: value for key, value in filters.items() if key != "proposal" and value
        }
        if view in {"reasoning", "requirements"}:
            required_tags["content_use"] = "context" if view == "reasoning" else "requirements"
        for artifact in artifacts.order_by("id").iterator(chunk_size=100):
            if str(artifact.unit.version.source_id) in excluded:
                continue
            text = workflow.artifact_text(artifact)
            title = Path(
                artifact.unit.version.observed_path or artifact.unit.version.source.display_path
            ).name
            if (
                not semantic
                and not exact
                and terms
                and not any(term in (text + " " + title).casefold() for term in terms)
            ):
                continue
            family = artifact.decision_event.decision.family
            if family.id not in decisions:
                decisions[family.id] = list(
                    m.Decision.objects.filter(family=family, status="resolved").prefetch_related(
                        Prefetch(
                            "decisionevent_set",
                            queryset=m.DecisionEvent.objects.order_by("revision"),
                            to_attr="writing_events",
                        )
                    )
                )
            if required_tags:
                tags, _ = labels(family, artifact.unit, decisions=decisions[family.id])
                if any(tags.get(key) != value for key, value in required_tags.items()):
                    continue
            if not services.factual_artifacts(user, collection_id, [artifact.id]).exists():
                continue
            candidates.append((artifact, text))
            if len(candidates) >= settings.APP["publication_retrieve_limit"]:
                break
        rows = [
            factual_item(
                item, text=text, decisions=decisions.get(item.decision_event.decision.family_id, [])
            )
            for item, text in candidates
        ]
    selected = []
    for row in rows:
        tags = row["labels"]
        if row["source_id"] in excluded:
            continue
        if exact and row["proposal"] != exact.identifier:
            continue
        if not exact and terms and not semantic:
            if not any(term in (row["text"] + " " + row["title"]).casefold() for term in terms):
                continue
        if view == "reasoning" and tags.get("content_use") != "context":
            continue
        if view == "requirements" and tags.get("content_use") != "requirements":
            continue
        if any(
            value and (row["proposal"] if key == "proposal" else tags.get(key)) != value
            for key, value in filters.items()
        ):
            continue
        row["score"] = sum(row["text"].casefold().count(term) for term in terms)
        selected.append(row)
    # Collapse only equal passages with equal scientific meaning; retain every location.
    groups = {}
    for row in sorted(selected, key=lambda item: (-item["score"], item["unit_id"])):
        identity = (row["text"], str(row["labels"]), row["proposal"], row["support_kind"])
        if identity in groups:
            groups[identity]["provenance"].append(row)
        else:
            groups[identity] = {**row, "provenance": [row]}
    return list(groups.values())


def context_and_versions(unit):
    neighbors = (
        m.ExtractedUnit.objects.filter(
            version=unit.version,
            extraction_run=unit.extraction_run,
            ordinal__gte=max(0, unit.ordinal - 1),
            ordinal__lte=unit.ordinal + 1,
        )
        .exclude(pk=unit.pk)
        .order_by("ordinal", "key")
    )
    versions = (
        m.ExtractedUnit.objects.filter(
            version__source=unit.version.source,
            key=unit.key,
        )
        .exclude(pk=unit.pk)
        .select_related("version")
        .order_by("-version__observed_at")
    )
    return neighbors, versions
