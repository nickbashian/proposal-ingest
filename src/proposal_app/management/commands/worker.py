import time

from django.conf import settings
from django.core.management.base import BaseCommand

from proposal_app.jobs import work_once


class Command(BaseCommand):
    help = "Process durable jobs (one worker by default); Ctrl+C stops polling."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        while True:
            worked = work_once()
            if options["once"]:
                return
            if not worked:
                time.sleep(settings.APP["poll_seconds"])
