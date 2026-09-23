"""Print an ID-only extraction coverage/sampling manifest for private review."""

import json
import uuid

from django.core.management.base import BaseCommand, CommandError

from proposal_app.extraction_audit import audit_collection
from proposal_app.models import Collection


class Command(BaseCommand):
    help = "Print source-version IDs and extraction states for private seed-family audit."

    def add_arguments(self, parser):
        parser.add_argument("--collection", required=True)
        parser.add_argument("--per-family", type=int, default=5)

    def handle(self, *args, **options):
        try:
            collection_id = uuid.UUID(options["collection"])
        except ValueError:
            raise CommandError("Collection must be a UUID") from None
        if not Collection.objects.filter(pk=collection_id).exists():
            raise CommandError("Collection not found")
        try:
            report = audit_collection(collection_id, per_family=options["per_family"])
        except ValueError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(json.dumps(report, sort_keys=True, indent=2))
