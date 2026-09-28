"""Read-only synthetic source to classification, plan, and curated publication."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from proposal_app import jobs, models as m, workflow


class Command(BaseCommand):
    help = "Run the fictional MVP-05b source through MVP-06 local publication."

    def handle(self, *args, **options):
        if settings.MODE != "local" or settings.APP["publication_backend"] != "local":
            raise CommandError("Fictional publication is local only")
        call_command("fixture_ai_ingest", stdout=self.stdout)
        for _ in range(settings.APP["classification_max_jobs_per_run"]):
            if not m.Job.objects.filter(kind="classify-unit", state="queued").exists():
                break
            if not jobs.work_once():
                raise CommandError("Classification worker stopped before the queue drained")
        if m.Job.objects.filter(kind="classify-unit", state="queued").exists():
            raise CommandError("Classification queue exceeds the configured demo bound")
        user = get_user_model().objects.get(username="fixture-owner")
        proposal = m.Proposal.objects.get(
            collection__name="Synthetic AI ingestion", identifier="FICTIONAL-05B"
        )
        try:
            generation = workflow.publish(user, proposal.id)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"proposal={proposal.id} generation={generation.id} state={generation.state} "
            f"artifacts={generation.expected_count}"
        )
