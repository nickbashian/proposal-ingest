from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from proposal_app import models as m, writing_demo


class Command(BaseCommand):
    help = "Rehearse five fictional writing tasks with separate voice and saved revisions."

    def add_arguments(self, parser):
        parser.add_argument("--update-source", action="store_true")

    def handle(self, *args, **options):
        if settings.MODE != "local" or settings.APP["publication_backend"] != "local":
            raise CommandError("Writing fixture is local only")
        user, _ = get_user_model().objects.get_or_create(username="fictional-writing-owner")
        m.Identity.objects.get_or_create(
            user=user, issuer="local", subject="fictional-writing-owner", defaults={"allowed": True}
        )
        collection, _ = m.Collection.objects.get_or_create(name="Fictional MVP-07 writing")
        m.CollectionAccess.objects.get_or_create(collection=collection, user=user)
        if options["update_source"]:
            writing_demo.update_source(user, collection)
            self.stdout.write(
                "Source updated. Saved citations remain historical; new use requires curation."
            )
        else:
            for session in writing_demo.rehearse(user, collection):
                self.stdout.write(f"/writing/{session.id}/ — {session.title}")
            self.stdout.write("Local sign-in subject: fictional-writing-owner")
