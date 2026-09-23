"""Run one configured, proposal-scoped source capture."""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from proposal_app import models as m
from proposal_app.adapters import ProviderFailure
from proposal_app.graph_source import GraphSourceAdapter
from proposal_app.source_sync import LocalSourceAdapter, sync_scope


class Command(BaseCommand):
    help = "Capture one local folder or read-only SharePoint root for one proposal/year."

    def add_arguments(self, parser):
        parser.add_argument("--collection", required=True, help="Existing collection UUID")
        parser.add_argument("--proposal", required=True, help="Proposal identifier")
        parser.add_argument("--year", required=True, type=int)
        parser.add_argument("--connector", required=True, choices=("local", "sharepoint"))
        parser.add_argument(
            "--root", required=True, help="Local folder path or Graph drive item ID"
        )
        parser.add_argument("--tenant", default="")
        parser.add_argument("--site", default="")
        parser.add_argument("--drive", default="")

    def handle(self, *args, **options):
        collection = m.Collection.objects.filter(pk=options["collection"]).first()
        if collection is None:
            raise CommandError("Collection does not exist")
        connector = options["connector"]
        if connector == "local":
            if settings.MODE != "local":
                raise CommandError("Local source adapter is development-only")
            try:
                root = Path(options["root"]).resolve(strict=True)
            except OSError:
                raise CommandError("Local root is unavailable") from None
            if not root.is_dir():
                raise CommandError("Local root must be a directory")
            if root.parent.name != str(options["year"]):
                raise CommandError(
                    "Local proposal root must be directly under the requested year folder"
                )
            tenant = options["tenant"] or "local"
            site = options["site"] or "local"
            drive = options["drive"] or str(root.anchor)
            adapter = LocalSourceAdapter(root)
            root_item = str(root)
        else:
            root_item = options["root"]
            try:
                adapter = GraphSourceAdapter.from_environment(
                    root_item_id=root_item,
                    max_download_bytes=settings.APP["max_snapshot_bytes"],
                )
                root_item_metadata = adapter.get_item(root_item)
            except (ValueError, ProviderFailure):
                raise CommandError("SharePoint scope or read access is unavailable") from None
            tenant, site, drive = adapter.tenant_id, adapter.site_id, adapter.drive_id
            path_parts = root_item_metadata.path.replace("\\", "/").rstrip("/").split("/")
            if (
                not root_item_metadata.is_folder
                or len(path_parts) < 2
                or path_parts[-2] != str(options["year"])
            ):
                raise CommandError(
                    "SharePoint root must be a proposal folder directly under the requested year"
                )
        if not 2000 <= options["year"] <= 2100:
            raise CommandError("Year is outside the supported range")
        proposal, _ = m.Proposal.objects.get_or_create(
            collection=collection, identifier=options["proposal"]
        )
        scope, _ = m.SourceScope.objects.get_or_create(
            collection=collection,
            connector=connector,
            tenant=tenant,
            site=site,
            drive=drive,
            root_item=root_item,
            proposal=proposal,
            year=options["year"],
        )
        try:
            run = sync_scope(scope, adapter)
        except ProviderFailure as exc:
            raise CommandError(exc.code) from None
        self.stdout.write(f"{run.id} {run.state} {run.counts}")
        if run.state != "completed":
            raise CommandError(f"Sync incomplete: {run.error_code}; rerun to resume")
