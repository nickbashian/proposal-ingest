"""Durable attempts, atomic budgets, fenced completion, and transactional delivery."""

import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from . import models as m
from .adapters import CallResult, ProviderFailure, adapter_for


def amount(value):
    value = Decimal(value)
    if not value.is_finite() or value < 0:
        raise ValueError("Cost must be finite and nonnegative")
    return value.quantize(Decimal("0.000001"))


def current(job, token):
    return job.state == "running" and job.lease_token == token and job.lease_until > timezone.now()


@transaction.atomic
def claim():
    now = timezone.now()
    job = (
        m.Job.objects.select_for_update(skip_locked=True)
        .filter(Q(state="queued", available_at__lte=now) | Q(state="running", lease_until__lte=now))
        .order_by("created_at")
        .first()
    )
    if job is None:
        return None
    if job.lease_token:
        m.Attempt.objects.filter(token=job.lease_token).update(state="expired", finished_at=now)
        m.UsageReservation.objects.filter(attempt__token=job.lease_token, state="reserved").update(
            state="unknown"
        )
    if job.attempts >= settings.APP["max_attempts"]:
        job.state, job.stop_reason = "failed", "attempt_limit"
        job.lease_token, job.lease_until = None, None
        job.save()
        return None
    job.attempts += 1
    job.lease_token = uuid.uuid4()
    job.lease_until = now + timedelta(seconds=settings.APP["lease_seconds"])
    job.state = "running"
    job.save()
    return m.Attempt.objects.create(job=job, number=job.attempts, token=job.lease_token)


@transaction.atomic
def heartbeat(attempt_id):
    attempt = m.Attempt.objects.get(pk=attempt_id)
    job = m.Job.objects.select_for_update().get(pk=attempt.job_id)
    if not current(job, attempt.token):
        return False
    job.lease_until = timezone.now() + timedelta(seconds=settings.APP["lease_seconds"])
    job.save(update_fields=["lease_until"])
    return True


@transaction.atomic
def reserve(attempt_id, estimate):
    estimate = amount(estimate)
    attempt = m.Attempt.objects.get(pk=attempt_id)
    job = m.Job.objects.select_for_update().get(pk=attempt.job_id)
    if (
        not current(job, attempt.token)
        or m.UsageReservation.objects.filter(attempt=attempt).exists()
    ):
        return None
    specs = [
        ("setup", settings.APP["setup_limit_usd"]),
        (timezone.now().strftime("month-%Y-%m"), settings.APP["monthly_limit_usd"]),
    ]
    # Stable order across every transaction; persistent caps are not reset on restart.
    accounts = []
    for key, limit in sorted(specs):
        m.BudgetAccount.objects.get_or_create(key=key, defaults={"limit": amount(limit)})
        accounts.append(m.BudgetAccount.objects.select_for_update().get(pk=key))
        # Lower configuration takes effect immediately; raising a persisted cap
        # requires an explicit operator change, never a process restart.
        if accounts[-1].limit > amount(limit):
            accounts[-1].limit = amount(limit)
            accounts[-1].save(update_fields=["limit"])
    spent = m.UsageReservation.objects.filter(attempt__job=job).aggregate(total=Sum("charged"))[
        "total"
    ] or Decimal(0)
    if spent + estimate > min(job.budget, amount(settings.APP["job_limit_usd"])) or any(
        account.committed + estimate > account.limit for account in accounts
    ):
        job.state, job.stop_reason = "budget_stopped", "reservation_exceeds_limit"
        job.lease_token, job.lease_until = None, None
        job.save()
        attempt.state, attempt.finished_at = "budget_stopped", timezone.now()
        attempt.save(update_fields=["state", "finished_at"])
        return None
    reservation = m.UsageReservation.objects.create(
        attempt=attempt, reserved=estimate, charged=estimate
    )
    for account in accounts:
        account.committed += estimate
        account.save()
    reservation.accounts.set(accounts)
    attempt.state = "dispatched"
    attempt.save()
    return reservation


def reconcile(attempt, result, failure):
    reservation = m.UsageReservation.objects.select_for_update().filter(attempt=attempt).first()
    if reservation is None or reservation.state == "reconciled":
        return
    if failure and failure.unknown:
        reservation.state = "unknown"
    else:
        actual = amount(result.cost if result else 0)
        delta = actual - reservation.charged
        for account in reservation.accounts.select_for_update().order_by("key"):
            account.committed += delta
            account.save()
        reservation.actual, reservation.charged = actual, actual
        reservation.state = "reconciled"
        reservation.usage = result.usage if result else {}
    reservation.save()


@transaction.atomic
def finish(attempt_id, *, result: CallResult | None = None, failure: ProviderFailure | None = None):
    attempt = m.Attempt.objects.get(pk=attempt_id)
    job = m.Job.objects.select_for_update().get(pk=attempt.job_id)
    # Late calls are accounted for even when they cannot commit application effects.
    reconcile(attempt, result, failure)
    if not current(job, attempt.token):
        return False
    attempt.finished_at = timezone.now()
    if failure:
        attempt.state = "unknown" if failure.unknown else "failed"
        job.stop_reason = failure.code
        if failure.quota:
            job.state = "quota_stopped"
        elif failure.code == "adapter_disabled":
            job.state = "disabled"
        elif failure.retryable and job.attempts < settings.APP["max_attempts"]:
            job.state = "queued"
            job.available_at = timezone.now() + timedelta(
                seconds=settings.APP["backoff_seconds"] * 2 ** (job.attempts - 1)
            )
        else:
            job.state = "failed"
    elif result is not None:
        reservation = m.UsageReservation.objects.filter(attempt=attempt).first()
        if reservation is None:
            raise ValueError("Completion requires a dispatch reservation")
        attempt.state = "succeeded"
        if amount(result.cost) > reservation.reserved:
            job.state, job.stop_reason = "budget_stopped", "provider_exceeded_reservation"
        else:
            job.state, job.result = "delivering", result.value
            m.Outbox.objects.get_or_create(job=job)
    else:
        raise ValueError("Completion needs a result or failure")
    job.lease_token, job.lease_until = None, None
    job.save()
    attempt.save()
    return True


@transaction.atomic
def deliver(job_id):
    """Exactly one database effect. Future remote effects require idempotent reconciliation."""
    job = m.Job.objects.select_for_update().get(pk=job_id)
    outbox = m.Outbox.objects.select_for_update().filter(job=job, delivered_at__isnull=True).first()
    if outbox is None or job.state != "delivering":
        return False
    if job.kind == "fixture-slice":
        from .workflow import deliver_fixture_import

        try:
            summary = deliver_fixture_import(job)
        except Exception as exc:  # noqa: BLE001 - delivery must fail closed
            job.state = "failed"
            job.stop_reason = (
                "delivery_denied"
                if isinstance(exc, PermissionDenied)
                else "delivery_invalid" if isinstance(exc, ValueError) else "delivery_error"
            )
            job.result = {}
            job.save(update_fields=["state", "stop_reason", "result"])
            outbox.delivered_at = timezone.now()
            outbox.save(update_fields=["delivered_at"])
            m.AuditRecord.objects.create(action="job.delivery_failed", object_id=job.id)
            return True
        job.result = {**job.result, "import": summary}
        job.save(update_fields=["result"])
    elif job.kind == "classify-unit":
        from .classification import deliver as deliver_classification

        try:
            summary = deliver_classification(job)
        except Exception:
            job.state = "failed"
            job.stop_reason = "delivery_error"
            job.result = {}
            job.save(update_fields=["state", "stop_reason", "result"])
            outbox.delivered_at = timezone.now()
            outbox.save(update_fields=["delivered_at"])
            m.AuditRecord.objects.create(action="job.delivery_failed", object_id=job.id)
            return True
        job.result = {**job.result, "classification": summary}
        job.save(update_fields=["result"])
    m.JobResult.objects.get_or_create(job=job, defaults={"value": job.result})
    outbox.delivered_at = timezone.now()
    outbox.save()
    job.state = "succeeded"
    job.stop_reason = ""
    job.save()
    m.AuditRecord.objects.create(action="job.completed", object_id=job.id)
    return True


def work_once():
    for job_id in m.Outbox.objects.filter(
        delivered_at__isnull=True, job__state="delivering"
    ).values_list("job_id", flat=True):
        deliver(job_id)
    attempt = claim()
    if attempt is None:
        return False
    try:
        adapter = adapter_for(attempt.job.kind)
    except ProviderFailure as failure:
        finish(attempt.id, failure=failure)
        return True
    estimate = (
        settings.APP["fixture_reservation_usd"]
        if attempt.job.kind != "classify-unit" or attempt.job.payload.get("mode") == "mock"
        else settings.APP["classification_estimate_usd_per_call"]["baseline"]
    )
    if reserve(attempt.id, estimate) is None:
        return True
    try:
        # Reservation commits before issuing any call. Cancellation after this point
        # treats this attempt as in flight; its completion remains fenced.
        result = adapter.execute(attempt.job.payload, idempotency_key=str(attempt.job.id))
        finish(attempt.id, result=result)
    except ProviderFailure as failure:
        finish(attempt.id, failure=failure)
    except Exception:
        finish(attempt.id, failure=ProviderFailure("unknown_outcome", retryable=True, unknown=True))
    deliver(attempt.job_id)
    return True
