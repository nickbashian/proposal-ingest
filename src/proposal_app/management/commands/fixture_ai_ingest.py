"""Provision and capture the fictional MVP-05b source through real app services."""

from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from proposal_app import models as m
from proposal_app.extraction_service import extract_version
from proposal_app.source_sync import LocalSourceAdapter, sync_scope


class Command(BaseCommand):
    help = "Capture, extract, and queue the fictional AI-ingestion demonstration."

    def handle(self, *args, **options):
        if settings.MODE != "local":
            raise CommandError("The fictional ingestion fixture is local only")
        root = Path(settings.ROOT / settings.APP["classification_demo_source_root"]).resolve()
        if not root.is_dir():
            raise CommandError("Fictional source fixture is unavailable")
        user, _ = get_user_model().objects.get_or_create(username="fixture-owner")
        user.set_unusable_password()
        user.save()
        identity, _ = m.Identity.objects.get_or_create(
            user=user, defaults={"issuer": "local", "subject": "fixture-owner", "allowed": True}
        )
        if (identity.issuer, identity.subject, identity.allowed) != (
            "local",
            "fixture-owner",
            True,
        ):
            raise CommandError(
                "Fixture identity is revoked or differs from the expected local user"
            )
        collection, _ = m.Collection.objects.get_or_create(name="Synthetic AI ingestion")
        m.CollectionAccess.objects.get_or_create(collection=collection, user=user)
        proposal, _ = m.Proposal.objects.get_or_create(
            collection=collection, identifier="FICTIONAL-05B"
        )
        scope, _ = m.SourceScope.objects.get_or_create(
            collection=collection,
            connector="local",
            tenant="local",
            site="local",
            drive=str(root.anchor),
            root_item=str(root),
            proposal=proposal,
            year=2025,
        )
        run = sync_scope(scope, LocalSourceAdapter(root))
        if run.state != "completed":
            raise CommandError(f"Fictional capture incomplete: {run.error_code}")
        versions = (
            m.SourceVersion.objects.filter(
                source__sourcepresence__scope=scope,
                source__sourcepresence__retired_at__isnull=True,
            )
            .select_related("source")
            .order_by("source_id", "-observed_at", "-id")
        )
        seen = set()
        for version in versions:
            if version.source_id in seen:
                continue
            seen.add(version.source_id)
            extract_version(user, version.id)
        queued = m.Job.objects.filter(
            collection=collection, kind="classify-unit", state="queued"
        ).count()
        self.stdout.write(
            f"collection={collection.id} captured={len(seen)} queued={queued} "
            f"review=/collections/{collection.id}/review/"
        )
