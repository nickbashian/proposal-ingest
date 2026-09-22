"""Real process and browser acceptance, entirely synthetic and on the test database."""

import os
import subprocess
import sys
import time
from decimal import Decimal
from urllib.parse import quote, urlunparse

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from playwright.sync_api import sync_playwright

from proposal_app import models as m, services


def child_environment():
    db = connection.settings_dict
    env = dict(os.environ)
    authority = (
        f"{quote(db['USER'], safe='')}:{quote(db['PASSWORD'], safe='')}@{db['HOST']}:{db['PORT']}"
    )
    env["DATABASE_URL"] = urlunparse(("postgresql", authority, "/" + db["NAME"], "", "", ""))
    env["JOB_LEASE_SECONDS"] = "2"
    env["PROPOSAL_LOCAL_AUTH_ENABLED"] = "true"
    return env


@pytest.fixture
def fixture_owner(transactional_db):
    user = get_user_model().objects.create_user(username="fixture-owner")
    m.Identity.objects.create(user=user, issuer="local", subject="fixture-owner", allowed=True)
    collection = m.Collection.objects.create(name="Synthetic restart acceptance")
    m.CollectionAccess.objects.create(collection=collection, user=user)
    return user, collection


def test_terminate_worker_restart_consistent_result(fixture_owner):
    user, collection = fixture_owner
    job = services.create_job(user, collection.id, "process-restart")
    # Instrument only the local provider latency. The real management worker claims,
    # reserves, dispatches, and is forcibly terminated without graceful cleanup.
    code = """
import os, time
os.environ['DJANGO_SETTINGS_MODULE'] = 'proposal_app.settings'
import django
django.setup()
from proposal_app.adapters import FixtureAdapter
original = FixtureAdapter.execute
def slow(self, *args, **kwargs):
    time.sleep(60)
    return original(self, *args, **kwargs)
FixtureAdapter.execute = slow
from django.core.management import call_command
call_command('worker', once=True)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        env=child_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 15
        while not m.UsageReservation.objects.filter(attempt__job=job).exists():
            if process.poll() is not None or time.monotonic() > deadline:
                raise AssertionError("Child worker failed to reserve")
            time.sleep(0.1)
        process.kill()
        process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
    time.sleep(2.1)
    subprocess.run(
        [sys.executable, "scripts/manage.py", "worker", "--once"],
        env=child_environment(),
        check=True,
        capture_output=True,
        timeout=20,
    )
    job.refresh_from_db()
    assert job.state == "succeeded"
    assert job.attempts == 2
    assert m.JobResult.objects.filter(job=job).count() == 1
    assert m.UsageReservation.objects.get(attempt__job=job, attempt__number=1).state == "unknown"
    assert m.UsageReservation.objects.get(attempt__job=job, attempt__number=2).actual == 0
    assert m.BudgetAccount.objects.get(pk="setup").committed == Decimal(
        settings.APP["fixture_reservation_usd"]
    )


def test_browser_authenticated_fixture_workflow(fixture_owner, live_server, monkeypatch):
    monkeypatch.setattr(settings, "LOCAL_AUTH", True)
    cache = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if not cache:
        from pathlib import Path

        monkeypatch.setenv(
            "PLAYWRIGHT_BROWSERS_PATH", str(Path.home() / ".codex/proposal-ingest/playwright")
        )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            response = page.goto(live_server.url + "/")
            assert response.status == 401
            page.goto(live_server.url + "/login/")
            page.get_by_role("button", name="Sign in locally").click()
            page.get_by_role("button", name="Create synthetic fixture job").click()
            page.wait_for_url("**/jobs/**")
            assert "queued" in page.locator("body").inner_text()
            subprocess.run(
                [sys.executable, "scripts/manage.py", "worker", "--once"],
                env=child_environment(),
                check=True,
                timeout=20,
                capture_output=True,
            )
            page.reload()
            assert "succeeded" in page.locator("body").inner_text()
            assert "reconciled" in page.locator("body").inner_text()
            page.get_by_role("button", name="Sign out").click()
            assert page.goto(live_server.url + "/").status == 401
        finally:
            browser.close()
