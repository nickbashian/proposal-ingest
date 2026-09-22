from django.conf import settings
from django.core.management.base import CommandError
from django.core.management.commands.runserver import Command as RunServer


class Command(RunServer):
    def inner_run(self, *args, **options):
        if settings.MODE != "local":
            raise CommandError("Use the production WSGI server in deployment mode")
        if self.addr not in {"127.0.0.1", "localhost", "::1"}:
            raise CommandError("Development server must bind to loopback")
        return super().inner_run(*args, **options)
