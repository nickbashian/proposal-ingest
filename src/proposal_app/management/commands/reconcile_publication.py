"""Retry a failed generation or verify deletion of a retired generation."""

from django.core.management.base import BaseCommand, CommandError

from proposal_app import models as m, publication


class Command(BaseCommand):
    help = "Reconcile publication, retired deletion, or a held recovery reindex."

    def add_arguments(self, parser):
        parser.add_argument("generation_id")
        parser.add_argument("--delete", action="store_true")
        parser.add_argument("--restore", action="store_true")
        parser.add_argument("--reindex-active", action="store_true")
        parser.add_argument("--activate-reindexed", action="store_true")

    def handle(self, *args, **options):
        generation = m.PublicationGeneration.objects.filter(pk=options["generation_id"]).first()
        if generation is None:
            raise CommandError("Publication generation was not found")
        actions = [
            name
            for name in ("delete", "restore", "reindex_active", "activate_reindexed")
            if options[name]
        ]
        if len(actions) > 1:
            raise CommandError("Choose one publication action")
        if options["reindex_active"]:
            generation = publication.prepare_reindex_active(generation.id)
            self.stdout.write(f"publication={generation.state} hold=required")
        elif options["activate_reindexed"]:
            generation = publication.activate_reindexed(generation.id)
            self.stdout.write(f"publication={generation.state} hold=required")
        elif options["restore"]:
            generation = publication.restore_verified(generation.id)
            self.stdout.write(f"publication={generation.state}")
        elif options["delete"]:
            generation = publication.cleanup_retired(generation.id)
            self.stdout.write(f"deletion={generation.deletion_state}")
        else:
            generation = publication.process(generation.id)
            self.stdout.write(f"publication={generation.state} failure={generation.failure}")
