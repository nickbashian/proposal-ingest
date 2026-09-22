import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from proposal_app import models as m, services


class Command(BaseCommand):
    help = "Create an allowlisted synthetic local identity, collection, and durable fixture job."

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
        collection, _ = m.Collection.objects.get_or_create(name="Synthetic foundation")
        m.CollectionAccess.objects.get_or_create(collection=collection, user=user)
        job = services.create_job(user, collection.id, "fixture-" + uuid.uuid4().hex)
        self.stdout.write(str(job.id))
