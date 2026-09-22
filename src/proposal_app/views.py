"""Small authenticated operator shell backed by the same services as workers."""

import uuid

from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import models as m, services


@require_GET
def home(request):
    collections = m.Collection.objects.filter(collectionaccess__user=request.user)
    jobs = m.Job.objects.filter(collection__in=collections).order_by("-created_at")[:30]
    return render(request, "proposal_app/home.html", {"collections": collections, "jobs": jobs})


@require_http_methods(["GET", "POST"])
def collection(request, collection_id):
    services.authorize(request.user, collection_id)
    if request.method == "POST":
        job = services.create_job(
            request.user, collection_id, request.POST.get("key") or str(uuid.uuid4())
        )
        return HttpResponseRedirect(f"/jobs/{job.id}/")
    return JsonResponse(
        {
            "sources": list(
                m.SourceItem.objects.filter(collection_id=collection_id).values(
                    "id", "display_path"
                )
            )
        }
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
            return HttpResponse(str(exc), status=409)
        return HttpResponseRedirect(request.path)
    return render(
        request,
        "proposal_app/job.html",
        {"job": obj, "usage": m.UsageReservation.objects.filter(attempt__job=obj)},
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
        return HttpResponse(str(exc), status=409)
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
        m.PublicationArtifact.objects.select_related("generation__proposal")
        .filter(pk=object_id)
        .first()
    )
    if obj is None:
        raise Http404
    services.authorize(request.user, obj.generation.proposal.collection_id)
    return JsonResponse(
        {"id": str(obj.id), "eligible": obj.eligible, "generation": str(obj.generation_id)}
    )
