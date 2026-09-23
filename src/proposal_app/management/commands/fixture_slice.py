from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from proposal_app import models as m, workflow


class Command(BaseCommand):
    help = "Provision the synthetic MVP-02 collection and enqueue its idempotent import."

    @transaction.atomic
    def handle(self, *args, **options):
        if settings.MODE != "local":
            raise CommandError("Fixture provisioning is local only")
        user, _ = get_user_model().objects.get_or_create(username="fixture-owner")
        user.set_unusable_password()
        user.save()
        identity, _ = m.Identity.objects.get_or_create(
            user=user, defaults={"issuer": "local", "subject": "fixture-owner", "allowed": True}
        )
        if (
            identity.issuer != "local"
            or identity.subject != "fixture-owner"
            or not identity.allowed
        ):
            raise CommandError(
                "Existing fixture identity is different or revoked; operator action required"
            )
        collection, _ = m.Collection.objects.get_or_create(name="Synthetic product slice")
        m.CollectionAccess.objects.get_or_create(collection=collection, user=user)
        job = workflow.enqueue_fixture_import(user, collection.id)
        self.stdout.write(f"{job.id} {job.state}")
