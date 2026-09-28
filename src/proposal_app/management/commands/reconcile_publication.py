"""Retry a failed generation or verify deletion of a retired generation."""

from django.core.management.base import BaseCommand, CommandError

from proposal_app import models as m, publication


class Command(BaseCommand):
    help = "Reconcile one staged/failed publication generation or retired deletion."

    def add_arguments(self, parser):
        parser.add_argument("generation_id")
        parser.add_argument("--delete", action="store_true")
        parser.add_argument("--restore", action="store_true")

    def handle(self, *args, **options):
        generation = m.PublicationGeneration.objects.filter(pk=options["generation_id"]).first()
        if generation is None:
            raise CommandError("Publication generation was not found")
        if options["delete"] and options["restore"]:
            raise CommandError("Choose deletion or restore")
        if options["restore"]:
            generation = publication.restore_verified(generation.id)
            self.stdout.write(f"publication={generation.state}")
        elif options["delete"]:
            generation = publication.cleanup_retired(generation.id)
            self.stdout.write(f"deletion={generation.deletion_state}")
        else:
            generation = publication.process(generation.id)
            self.stdout.write(f"publication={generation.state} failure={generation.failure}")
