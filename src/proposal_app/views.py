"""Small authenticated operator shell backed by the same services as workers."""

import uuid
import shutil
import io
import json
from urllib.parse import urlencode

from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import curation, extraction_service, models as m, services, workflow
from .storage import LocalObjectStorage
from django.conf import settings


def conflict(error):
    return HttpResponse(str(error), status=409, content_type="text/plain; charset=utf-8")


@require_GET
def home(request):
    collections = m.Collection.objects.filter(collectionaccess__user=request.user)
    jobs = m.Job.objects.filter(collection__in=collections).order_by("-created_at")[:30]
    return render(request, "proposal_app/home.html", {"collections": collections, "jobs": jobs})


@require_http_methods(["GET", "POST"])
def collection(request, collection_id):
    services.authorize(request.user, collection_id)
    if request.method == "POST":
        action = request.POST.get("action", "fixture-job")
        try:
            if action == "import-fixture":
                job = workflow.enqueue_fixture_import(request.user, collection_id)
                return HttpResponseRedirect(f"/jobs/{job.id}/")
            if action == "review":
                workflow.answer_inclusion(
                    request.user,
                    request.POST.get("decision_id"),
                    int(request.POST.get("revision", 0)),
                    request.POST.get("treatment", ""),
                )
                return HttpResponseRedirect(request.path)
            if action == "publish":
                workflow.publish(request.user, request.POST.get("proposal_id"))
                return HttpResponseRedirect(request.path)
            if action == "new-draft":
                session = services.create_draft(
                    request.user,
                    collection_id,
                    request.POST.get("title", "Synthetic evidence draft"),
                )
                return HttpResponseRedirect(f"/writing/{session.id}/")
            if action != "fixture-job":
                raise ValueError("Unknown collection action")
            job = services.create_job(
                request.user, collection_id, request.POST.get("key") or str(uuid.uuid4())
            )
            return HttpResponseRedirect(f"/jobs/{job.id}/")
        except (ValueError, ValidationError) as exc:
            return conflict(exc)
    sources = list(
        m.SourceItem.objects.filter(collection_id=collection_id)
        .prefetch_related(
            "sourceversion_set__extractedunit_set",
            "proposalmembership_set__family__proposal",
        )
        .order_by("display_path")
    )
    rows = []
    for source in sources:
        versions = list(source.sourceversion_set.all())
        version_scopes = [f"version:{version.id}" for version in versions]
        units = [unit for version in versions for unit in version.extractedunit_set.all()]
        memberships = sorted(
            source.proposalmembership_set.all(),
            key=lambda membership: (
                membership.family.proposal.identifier,
                membership.family.key,
            ),
        )
        for membership in memberships:
            family = membership.family
            decision = (
                m.Decision.objects.filter(
                    family=family,
                    scope__in=version_scopes,
                    field="publication",
                    kind="inclusion",
                )
                .order_by("-created_at")
                .first()
            )
            latest_event = (
                m.DecisionEvent.objects.filter(decision=decision).order_by("-revision").first()
                if decision
                else None
            )
            display_disposition = "awaiting_decision"
            display_reason = ""
            if latest_event:
                display_disposition = {
                    "include": "included",
                    "exclude": "excluded",
                }.get(latest_event.value.get("treatment"), "awaiting_decision")
                display_reason = latest_event.rationale
            rows.append(
                {
                    "source": source,
                    "family": family,
                    "decision": decision,
                    "disposition": display_disposition,
                    "disposition_reason": display_reason,
                    "units": units,
                    "versions": versions,
                    "reviewable": bool(
                        decision
                        and (
                            decision.revision == 0
                            or not latest_event
                            or not latest_event.value.get("fixture_default")
                        )
                    ),
                }
            )
    proposals = m.Proposal.objects.filter(collection_id=collection_id).order_by("identifier")
    drafts = m.DraftSession.objects.filter(
        collection_id=collection_id, owner=request.user, deleted_at__isnull=True
    ).order_by("-created_at")
    return render(
        request,
        "proposal_app/collection.html",
        {
            "collection": m.Collection.objects.get(pk=collection_id),
            "rows": rows,
            "proposals": proposals,
            "drafts": drafts,
            "retrieval_label": workflow.LOCAL_RETRIEVAL_LABEL,
            "drafting_label": workflow.LOCAL_DRAFTING_LABEL,
            "review_queue": curation.review_queue(collection_id),
        },
    )


@require_GET
def review_queue(request, collection_id):
    services.authorize(request.user, collection_id)
    queue = curation.review_queue(collection_id)
    return render(
        request,
        "proposal_app/review_queue.html",
        {
            "collection": m.Collection.objects.get(pk=collection_id),
            "issues": queue["all"] if request.GET.get("all") == "1" else queue["visible"],
            "hidden_count": 0 if request.GET.get("all") == "1" else queue["hidden_count"],
            "critical_count": queue["critical_count"],
        },
    )


@require_http_methods(["GET", "POST"])
def review_decision(request, decision_id):
    decision = m.Decision.objects.select_related("family__proposal").filter(pk=decision_id).first()
    if decision is None:
        raise Http404
    services.authorize(request.user, decision.family.proposal.collection_id)
    if decision.field not in curation.DIMENSIONS | {"voice_approval"}:
        raise Http404
    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            expected = int(request.POST.get("revision", "-1"))
            value = None
            if action == "edit":
                if decision.field == "treatment":
                    treatment = request.POST.get("treatment", "")
                    value = {"treatment": treatment}
                    if treatment == "partial":
                        value["selected_units"] = request.POST.getlist("selected_units")
                    elif treatment == "summary":
                        value.update(
                            summary=request.POST.get("summary", ""),
                            source_units=request.POST.getlist("selected_units"),
                            voice_eligible=False,
                        )
                elif decision.field == "voice_approval":
                    value = {"approved": request.POST.get("approved") == "true"}
                else:
                    value = {"value": json.loads(request.POST.get("value", "null"))}
            elif action == "reject" and request.POST.get("alternative"):
                value = json.loads(request.POST["alternative"])
            curation.review(
                request.user,
                decision.id,
                expected,
                action,
                value=value,
                rationale=request.POST.get("rationale", ""),
            )
        except (ValueError, json.JSONDecodeError) as exc:
            return conflict(exc)
        return HttpResponseRedirect(request.path)
    curation._scope(decision.family, decision.scope)
    evidence = list(
        m.ExtractedUnit.objects.filter(id__in=decision.recommendation_evidence).select_related(
            "version__source"
        )
    )
    affected = list(
        m.ExtractedUnit.objects.filter(id__in=decision.affected_units).select_related(
            "version__source"
        )
    )
    scope_kind, scope_version, _ = curation._scope(decision.family, decision.scope)
    if scope_kind == "family":
        selectable = m.ExtractedUnit.objects.filter(
            version__source__proposalmembership__family=decision.family,
            extraction_run__active=True,
        ).distinct()
    elif scope_kind == "entity":
        selectable = m.ExtractedUnit.objects.filter(
            classificationfact__family=decision.family,
            classificationfact__entity_key=decision.scope.removeprefix("entity:"),
            extraction_run__active=True,
        ).distinct()
    elif scope_kind == "unit":
        selectable = m.ExtractedUnit.objects.filter(pk=decision.scope.removeprefix("unit:"))
    else:
        selectable = m.ExtractedUnit.objects.filter(
            version=scope_version, extraction_run__active=True
        )
        if scope_kind == "section":
            selectable = selectable.filter(locator__section=decision.scope.split(":", 2)[2])
    scope_count = selectable.count()
    selectable = list(
        selectable.order_by("ordinal", "key")[: settings.APP["curation_max_evidence_units"]]
    )
    prior = list(m.DecisionEvent.objects.filter(decision=decision).order_by("-revision")[:10])
    return render(
        request,
        "proposal_app/review_decision.html",
        {
            "decision": decision,
            "evidence": evidence,
            "affected": affected,
            "selectable": selectable,
            "prior": prior,
            "scope_kind": scope_kind,
            "scope_count": scope_count,
            "preview_limited": scope_count > len(selectable),
            "recommendation_json": json.dumps(decision.recommendation),
        },
    )


@require_http_methods(["GET", "POST"])
def job(request, object_id):
    obj = m.Job.objects.filter(pk=object_id).first()
    if obj is None:
        raise Http404
    services.authorize(request.user, obj.collection_id)
    if request.method == "POST":
        try:
            services.control_job(request.user, object_id, request.POST.get("action"))
        except ValueError as exc:
            return conflict(exc)
        return HttpResponseRedirect(request.path)
    return render(
        request,
        "proposal_app/job.html",
        {"job": obj, "usage": m.UsageReservation.objects.filter(attempt__job=obj)},
    )


@require_http_methods(["GET", "POST"])
def writing(request, object_id):
    session = services.owned(request.user, m.DraftSession, object_id)
    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action == "pin":
                workflow.pin_evidence(request.user, session.id, request.POST.get("artifact_id"))
            elif action == "generate":
                workflow.generate(request.user, session.id, request.POST.get("prompt", ""))
            elif action == "edit":
                workflow.edit(
                    request.user,
                    session.id,
                    int(request.POST.get("revision", 0)),
                    request.POST.get("text", ""),
                )
            elif action == "export":
                _, text, extension = workflow.export(
                    request.user,
                    session.id,
                    request.POST.get("format", "markdown"),
                    request.build_absolute_uri("/"),
                )
                content_type = (
                    "text/markdown; charset=utf-8"
                    if extension == "md"
                    else "text/plain; charset=utf-8"
                )
                response = HttpResponse(text, content_type=content_type)
                response["Content-Disposition"] = f'attachment; filename="draft.{extension}"'
                return response
            else:
                raise ValueError("Unknown writing action")
        except (ValueError, ValidationError) as exc:
            return conflict(exc)
        query = request.POST.get("query", "")
        suffix = "?" + urlencode({"q": query}) if query else ""
        return HttpResponseRedirect(request.path + suffix)
    query = request.GET.get("q", "")
    latest = m.DraftRevision.objects.filter(session=session).order_by("-number").first()
    return render(
        request,
        "proposal_app/writing.html",
        {
            "session": session,
            "query": query,
            "results": workflow.search(request.user, session.collection_id, query),
            "pins": m.EvidencePin.objects.filter(session=session).select_related(
                "artifact__unit__version__source"
            ),
            "latest": latest,
            "revisions": m.DraftRevision.objects.filter(session=session).order_by("-number"),
            "retrieval_label": workflow.LOCAL_RETRIEVAL_LABEL,
            "drafting_label": workflow.LOCAL_DRAFTING_LABEL,
        },
    )


DRAFT_MODELS = {
    "sessions": m.DraftSession,
    "revisions": m.DraftRevision,
    "packets": m.EvidencePacket,
    "exports": m.DraftExport,
}


@require_http_methods(["GET", "POST", "DELETE"])
def draft(request, kind, object_id, action="read"):
    model = DRAFT_MODELS.get(kind)
    if model is None:
        raise Http404
    # Resolve authorization before any action or validation, even unsupported operations.
    services.owned(request.user, model, object_id)
    if request.method == "GET" and action != "read":
        return HttpResponse(status=405)
    if request.method == "DELETE":
        action = "delete"
    try:
        obj = services.draft_action(
            request.user,
            model,
            object_id,
            action,
            text=request.POST.get("text", ""),
            expected_revision=int(request.POST.get("revision", 0)),
        )
    except ValueError as exc:
        return conflict(exc)
    if isinstance(obj, m.DraftExport):
        response = HttpResponse(obj.text, content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="draft.txt"'
        return response
    data = {"id": str(obj.id)}
    if isinstance(obj, m.DraftSession):
        data.update(title=obj.title, revision=obj.revision)
    elif isinstance(obj, m.DraftRevision):
        data.update(text=obj.text, number=obj.number)
    elif isinstance(obj, m.EvidencePacket):
        data["payload"] = obj.payload
    return JsonResponse(data)


@require_POST
def new_draft(request, collection_id):
    session = services.create_draft(
        request.user, collection_id, request.POST.get("title", "Untitled")
    )
    return JsonResponse({"id": str(session.id)}, status=201)


@require_GET
def artifact(request, object_id):
    obj = (
        m.PublicationArtifact.objects.select_related(
            "generation__proposal", "unit__version__source"
        )
        .filter(pk=object_id)
        .first()
    )
    if obj is None:
        raise Http404
    services.authorize(request.user, obj.generation.proposal.collection_id)
    return render(
        request,
        "proposal_app/artifact.html",
        {
            "artifact": obj,
            "locator_label": workflow.locator_label(obj.unit.locator),
            "withdrawn": not obj.eligible or obj.generation.state != "active",
        },
    )


@require_http_methods(["GET", "POST"])
def source_inspector(request, version_id):
    version = m.SourceVersion.objects.select_related("source", "blob").filter(pk=version_id).first()
    if version is None:
        raise Http404
    services.authorize(request.user, version.source.collection_id)
    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action == "extract":
                acted_run = extraction_service.extract_version(
                    request.user, version.id, force=request.POST.get("force") == "true"
                )
            elif action == "request-visual":
                figure_id = request.POST.get("figure_id") or None
                run_id = request.POST.get("run_id")
                if figure_id:
                    figure = m.FigureAsset.objects.filter(
                        pk=figure_id, run_id=run_id, run__version=version
                    ).first()
                    if figure is None:
                        raise Http404
                    locator = figure.locator
                else:
                    locator = {"page": int(request.POST.get("page", "0"))}
                task = extraction_service.request_visual(
                    request.user,
                    run_id,
                    kind=request.POST.get("kind", ""),
                    locator=locator,
                    figure_id=figure_id,
                    expected_version_id=version.id,
                )
                acted_run = task.run
            elif action == "complete-visual":
                task = extraction_service.complete_visual(
                    request.user,
                    request.POST.get("task_id"),
                    text=request.POST.get("interpretation", ""),
                    source_check=request.POST.get("source_check", ""),
                    expected_version_id=version.id,
                )
                acted_run = task.run
            elif action == "run-ocr":
                task = extraction_service.run_selective_ocr(
                    request.user, request.POST.get("task_id"), expected_version_id=version.id
                )
                acted_run = task.run
            else:
                raise ValueError("Unknown inspector action")
        except (ValueError, ValidationError) as exc:
            return conflict(exc)
        return HttpResponseRedirect(f"{request.path}?{urlencode({'run': str(acted_run.id)})}")
    runs = list(m.ExtractionRun.objects.filter(version=version).order_by("-number"))
    selected = runs[0] if runs else None
    if request.GET.get("run"):
        selected = next((run for run in runs if str(run.id) == request.GET["run"]), None)
        if selected is None:
            raise Http404
    units = (
        list(m.ExtractedUnit.objects.filter(extraction_run=selected).order_by("ordinal", "key"))
        if selected
        else []
    )
    rows = []
    for index, unit in enumerate(units):
        rows.append(
            {
                "unit": unit,
                "locator_label": workflow.locator_label(unit.locator),
                "before": units[index - 1].text if index else "",
                "after": units[index + 1].text if index + 1 < len(units) else "",
            }
        )
    figures = m.FigureAsset.objects.filter(run=selected).order_by("key") if selected else []
    tasks = (
        m.VisualInspection.objects.filter(run=selected).order_by("created_at") if selected else []
    )
    return render(
        request,
        "proposal_app/source_inspector.html",
        {
            "version": version,
            "runs": runs,
            "selected": selected,
            "rows": rows,
            "figures": figures,
            "tasks": tasks,
            "ocr_available": bool(
                settings.APP.get("extraction_ocr_executable")
                and shutil.which(settings.APP["extraction_ocr_executable"])
            ),
        },
    )


@require_GET
def unit_inspector(request, unit_id):
    unit = (
        m.ExtractedUnit.objects.select_related("version__source", "extraction_run")
        .filter(pk=unit_id)
        .first()
    )
    if unit is None:
        raise Http404
    services.authorize(request.user, unit.version.source.collection_id)
    return render(
        request,
        "proposal_app/unit_inspector.html",
        {"unit": unit, "locator_label": workflow.locator_label(unit.locator)},
    )


@require_GET
def figure_image(request, figure_id):
    figure = (
        m.FigureAsset.objects.select_related("run__version__source", "blob")
        .filter(pk=figure_id)
        .first()
    )
    if figure is None:
        raise Http404
    services.authorize(request.user, figure.run.version.source.collection_id)
    if figure.mime_type not in {"image/png", "image/jpeg", "image/tiff", "image/bmp"}:
        raise Http404
    content = LocalObjectStorage(settings.LOCAL_STORAGE_ROOT).get(figure.blob.storage_key)
    if request.GET.get("preview") == "1" and figure.mime_type in {"image/tiff", "image/bmp"}:
        from PIL import Image, UnidentifiedImageError

        try:
            with Image.open(io.BytesIO(content)) as image:
                if image.width * image.height > settings.APP["extraction_max_render_pixels"]:
                    raise ValueError("Figure exceeds preview pixel limit")
                output = io.BytesIO()
                image.convert("RGB").save(output, format="PNG")
                content = output.getvalue()
        except (OSError, UnidentifiedImageError, ValueError, Image.DecompressionBombError):
            raise Http404 from None
        mime_type = "image/png"
    else:
        mime_type = figure.mime_type
    response = HttpResponse(content, content_type=mime_type)
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_GET
def source_original(request, version_id):
    version = m.SourceVersion.objects.select_related("source", "blob").filter(pk=version_id).first()
    if version is None:
        raise Http404
    services.authorize(request.user, version.source.collection_id)
    content = LocalObjectStorage(settings.LOCAL_STORAGE_ROOT).get(version.blob.storage_key)
    suffix = extraction_service._snapshot_name(version).rsplit(".", 1)[-1].casefold()
    if suffix not in {"pdf", "docx", "pptx", "xlsx", "csv", "txt", "md"}:
        suffix = "bin"
    response = HttpResponse(content, content_type="application/octet-stream")
    response["Content-Disposition"] = f'attachment; filename="source-version.{suffix}"'
    response["X-Content-Type-Options"] = "nosniff"
    return response
