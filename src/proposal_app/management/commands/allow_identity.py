"""Explicit operator provisioning; successful OIDC never auto-enrolls a user."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from proposal_app import models as m


class Command(BaseCommand):
    help = "Allow/revoke an exact OIDC issuer + subject and assign collection access."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--issuer", required=True)
        parser.add_argument("--subject", required=True)
        parser.add_argument("--collection", required=True)
        parser.add_argument("--revoke", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["revoke"]:
            identity = m.Identity.objects.filter(
                user__username=options["username"],
                issuer=options["issuer"],
                subject=options["subject"],
            ).first()
            if identity is None:
                raise CommandError("No matching identity to revoke")
            identity.allowed = False
            identity.save(update_fields=["allowed"])
            m.CollectionAccess.objects.filter(
                user=identity.user, collection__name=options["collection"]
            ).delete()
            m.AuditRecord.objects.create(action="identity.revoked", object_id=identity.id)
            self.stdout.write("Identity access updated.")
            return
        user, _ = get_user_model().objects.get_or_create(username=options["username"])
        identity, _ = m.Identity.objects.get_or_create(
            user=user, defaults={"issuer": options["issuer"], "subject": options["subject"]}
        )
        if identity.issuer != options["issuer"] or identity.subject != options["subject"]:
            raise CommandError("Existing identity differs; refusing reassignment")
        identity.allowed = True
        identity.save()
        collection, _ = m.Collection.objects.get_or_create(name=options["collection"])
        m.CollectionAccess.objects.get_or_create(user=user, collection=collection)
        m.AuditRecord.objects.create(
            action="identity.allowed",
            object_id=identity.id,
        )
        self.stdout.write("Identity access updated.")
