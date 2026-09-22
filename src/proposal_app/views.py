"""Small authenticated operator shell backed by the same services as workers."""

import uuid
from urllib.parse import urlencode

from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import models as m, services, workflow


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
        .prefetch_related("sourceversion_set__extractedunit_set")
        .order_by("display_path")
    )
    rows = []
    for source in sources:
        decision = m.Decision.objects.filter(scope=f"source:{source.id}").first()
        latest_event = (
            m.DecisionEvent.objects.filter(decision=decision).order_by("-revision").first()
            if decision
            else None
        )
        units = [
            unit
            for version in source.sourceversion_set.all()
            for unit in version.extractedunit_set.all()
        ]
        rows.append(
            {
                "source": source,
                "decision": decision,
                "units": units,
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
                    request.user, session.id, request.POST.get("format", "markdown")
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
