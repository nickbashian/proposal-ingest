"""Fictional source-backed writing rehearsal; no provider or private archive access."""

import hashlib
import json

from django.conf import settings
from django.core.exceptions import PermissionDenied

from . import curation, drafting, models as m, services, workflow


def load(user, collection):
    if settings.MODE != "local" or settings.APP["publication_backend"] != "local":
        raise PermissionDenied("Writing fixture is local only")
    fixture = json.loads(
        (settings.ROOT / settings.APP["drafting_demo_path"]).read_text(encoding="utf-8")
    )
    if fixture.get("synthetic") is not True:
        raise ValueError("Writing demo requires a synthetic fixture")
    for item in fixture["items"]:
        version = services.observe_source(
            user,
            collection.id,
            identity={
                "connector": "writing-fixture",
                "tenant": str(collection.id),
                "site": "fictional",
                "drive": "fictional",
                "item": item["key"],
            },
            path=f"2025/{fixture['proposal']}/{item['key']}.txt",
            observation_key=fixture["revision"],
            content=item["text"].encode(),
            proposal=fixture["proposal"],
            family="fictional-writing",
            upstream_version=fixture["revision"],
        )
        run, _ = m.ExtractionRun.objects.get_or_create(
            version=version,
            number=1,
            defaults={
                "fingerprint": hashlib.sha256(item["text"].encode()).hexdigest(),
                "extractor_revision": "writing-fixture-v1",
                "parser": "synthetic",
                "state": "succeeded",
                "active": True,
            },
        )
        unit, _ = m.ExtractedUnit.objects.get_or_create(
            version=version,
            extractor_revision=run.extractor_revision,
            key=item["key"],
            defaults={
                "text": item["text"],
                "extraction_run": run,
                "support_kind": "voice" if item["use"] == "voice" else "factual",
                "locator": {"section": item["key"], "paragraph": 1},
                "warnings": ["Fictional demonstration; no real scientific evidence."],
            },
        )
        family = m.VersionFamily.objects.get(
            proposal__collection=collection, proposal__identifier=fixture["proposal"]
        )
        values = {
            "treatment": {"treatment": "excluded" if item.get("excluded") else "full"},
            "content_use": {"value": item["use"]},
            "claim_type": {"value": item["claim_type"]},
            "chemistry": {"value": "sodium"},
            "conditions": {
                "value": {"temperature": "room temperature", "cell": "matched fictional cell"}
            },
            "source_role": {
                "value": "solicitation" if item["use"] == "requirements" else "technical"
            },
            "temporal_meaning": {"value": "historical"},
        }
        if item["use"] == "voice":
            values["voice_approval"] = {"approved": True}
        for field, value in values.items():
            decision = curation.recommend(
                user,
                family.id,
                f"unit:{unit.id}",
                field,
                "curation",
                value=value,
                rationale="Source-checked fictional fixture label",
                evidence=[str(unit.id)],
                affected_units=[str(unit.id)],
            )
            if decision.revision == 0:
                curation.review(
                    user,
                    decision.id,
                    0,
                    "edit",
                    value=value,
                    rationale="Explicit fictional fixture review",
                )
        curation.build_plan(user, family.id, version.id)
    generation = workflow.publish(user, family.proposal_id)
    return fixture, generation


def rehearse(user, collection):
    fixture, generation = load(user, collection)
    artifacts = {
        artifact.unit.key: artifact
        for artifact in m.PublicationArtifact.objects.filter(generation=generation).select_related(
            "unit"
        )
    }
    voice = m.ExtractedUnit.objects.get(
        version__source__collection=collection,
        version__source__connector="writing-fixture",
        key="voice",
    )
    sessions = []
    for index, task in enumerate(fixture["tasks"], 1):
        title = f"Fictional writing task {index}: {task['mode']}"
        session = m.DraftSession.objects.filter(
            collection=collection, owner=user, title=title, deleted_at__isnull=True
        ).first()
        if session is None:
            session = services.create_draft(user, collection.id, title)
            for key in task["sources"]:
                workflow.pin_evidence(user, session.id, artifacts[key].id)
            drafting.pin_voice(user, session.id, voice.id)
            workflow.generate(
                user,
                session.id,
                task["prompt"],
                task={
                    "mode": task["mode"],
                    "audience": "Fictional grant reviewer",
                    "length": "Brief",
                    "assertions": task.get("assertions", ""),
                },
            )
        sessions.append(session)
    if not sessions:
        return sessions
    last = sessions[-1]
    latest = m.DraftRevision.objects.filter(session=last).order_by("-number").first()
    if latest is not None and latest.number == 1:
        workflow.edit(
            user,
            last.id,
            1,
            latest.text + "\nUser-authored transition: this proposed experiment needs review.",
        )
    return sessions


def update_source(user, collection):
    source = m.SourceItem.objects.get(
        collection=collection, connector="writing-fixture", item="results"
    )
    family = m.VersionFamily.objects.get(proposalmembership__source=source)
    return services.observe_source(
        user,
        collection.id,
        identity={
            key: getattr(source, key) for key in ("connector", "tenant", "site", "drive", "item")
        },
        path=source.display_path,
        observation_key="mvp07-fictional-v2",
        content=b"An updated fictional report awaits curation.",
        proposal=family.proposal.identifier,
        family=family.key,
        upstream_version="mvp07-fictional-v2",
    )
