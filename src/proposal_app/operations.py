"""Collection-scoped operational summaries without provider or source payloads."""

from decimal import Decimal

from django.db.models import Count, Q, Sum

from . import models as m, services


def dashboard(user, collection_id):
    """Return persisted job and usage state visible to this collection member."""
    services.authorize(user, collection_id)
    visible = m.Job.objects.filter(collection_id=collection_id).filter(
        ~Q(kind="draft-generation") | Q(creator=user)
    )
    states = dict(visible.values_list("state").annotate(count=Count("id")))
    kinds = dict(visible.values_list("kind").annotate(count=Count("id")))
    usage = (
        m.UsageReservation.objects.filter(attempt__job__in=visible)
        .values("attempt__job__kind")
        .annotate(
            calls=Count("id"),
            reserved=Sum("reserved"),
            accounted=Sum("charged"),
            recorded=Sum("actual"),
            unreported=Count("id", filter=Q(actual__isnull=True)),
        )
        .order_by("attempt__job__kind")
    )
    spending = [
        {
            "kind": row["attempt__job__kind"],
            "jobs": kinds.get(row["attempt__job__kind"], 0),
            "calls": row["calls"],
            "reserved": row["reserved"] or Decimal("0"),
            "accounted": row["accounted"] or Decimal("0"),
            "recorded": row["recorded"],
            "unreported": row["unreported"],
        }
        for row in usage
    ]
    recent = list(
        visible.only(
            "id", "collection_id", "kind", "state", "attempts", "stop_reason", "created_at"
        ).order_by("-created_at")[:50]
    )
    return {
        "states": states,
        "job_count": sum(states.values()),
        "spending": spending,
        "recent": recent,
    }
