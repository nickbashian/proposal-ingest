"""Stage old CLI exports against captured application source identities."""

import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import PermissionDenied

from proposal_app import legacy_import, models as m


class Command(BaseCommand):
    help = "Validate legacy exports; --commit preserves exact originals and staged lineage."

    def add_arguments(self, parser):
        parser.add_argument("--collection", required=True, help="Existing collection UUID")
        parser.add_argument("--user", required=True, help="Allowed importing username")
        parser.add_argument("--inventory", required=True, help="Legacy inventory CSV or JSONL")
        parser.add_argument("--metadata", help="Optional document metadata JSONL")
        parser.add_argument("--answers", help="Optional answers CSV")
        parser.add_argument("--commit", action="store_true", help="Stage the validated bundle")

    def handle(self, *args, **options):
        try:
            user = get_user_model().objects.get(username=options["user"])
            collection = m.Collection.objects.get(pk=options["collection"])
            kwargs = {
                "inventory": options["inventory"],
                "metadata": options["metadata"],
                "answers": options["answers"],
            }
            if options["commit"]:
                staged, created = legacy_import.commit_legacy_import(user, collection.id, **kwargs)
                report = staged.records
            else:
                report, _ = legacy_import.prepare_legacy_import(user, collection.id, **kwargs)
                created = False
        except (
            OSError,
            UnicodeError,
            ValueError,
            PermissionDenied,
            m.Collection.DoesNotExist,
            get_user_model().DoesNotExist,
        ) as exc:
            raise CommandError(str(exc)) from exc
        # Paths, IDs and private text remain in the database report, not terminal logs.
        self.stdout.write(
            json.dumps(
                {
                    "bundle_sha256": report["bundle_sha256"],
                    "inventory": report["inventory"],
                    "metadata": report["metadata"],
                    "answers": report["answers"],
                    "staged": bool(options["commit"]),
                    "created": created,
                },
                sort_keys=True,
            )
        )
