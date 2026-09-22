"""Database contracts. Sources, observations, bytes, and memberships are distinct."""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Record(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        abstract = True


class Collection(Record):
    name = models.CharField(max_length=200, unique=True)


class Identity(Record):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    issuer = models.CharField(max_length=300)
    subject = models.CharField(max_length=300)
    allowed = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["issuer", "subject"], name="identity_subject")
        ]


class CollectionAccess(Record):
    collection = models.ForeignKey(Collection, on_delete=models.PROTECT)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["collection", "user"], name="collection_user")
        ]


class SourceItem(Record):
    collection = models.ForeignKey(Collection, on_delete=models.PROTECT)
    connector = models.CharField(max_length=80)
    tenant = models.CharField(max_length=200)
    site = models.CharField(max_length=200)
    drive = models.CharField(max_length=200)
    item = models.CharField(max_length=500)
    display_path = models.TextField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["connector", "tenant", "site", "drive", "item"], name="source_identity"
            )
        ]


class ContentBlob(Record):
    sha256 = models.CharField(max_length=64, unique=True)
    size = models.PositiveBigIntegerField()
    storage_key = models.CharField(max_length=500, blank=True)


class SourceVersion(Record):
    source = models.ForeignKey(SourceItem, on_delete=models.PROTECT)
    observation_key = models.CharField(max_length=200)
    upstream_version = models.CharField(max_length=200, null=True)
    etag = models.CharField(max_length=300, null=True)
    blob = models.ForeignKey(ContentBlob, on_delete=models.PROTECT)
    observed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "observation_key"], name="source_observation")
        ]


class Proposal(Record):
    collection = models.ForeignKey(Collection, on_delete=models.PROTECT)
    identifier = models.CharField(max_length=200)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["collection", "identifier"], name="proposal_identity")
        ]


class VersionFamily(Record):
    proposal = models.ForeignKey(Proposal, on_delete=models.PROTECT)
    key = models.CharField(max_length=200)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["proposal", "key"], name="family_identity")]


class ProposalMembership(Record):
    source = models.ForeignKey(SourceItem, on_delete=models.PROTECT)
    family = models.ForeignKey(VersionFamily, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "family"], name="source_membership")
        ]


class ExtractedUnit(Record):
    version = models.ForeignKey(SourceVersion, on_delete=models.PROTECT)
    extractor_revision = models.CharField(max_length=100)
    key = models.CharField(max_length=200)
    locator = models.JSONField()
    text = models.TextField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["version", "extractor_revision", "key"], name="version_locator"
            )
        ]


class Decision(Record):
    family = models.ForeignKey(VersionFamily, on_delete=models.PROTECT)
    scope = models.CharField(max_length=200)
    field = models.CharField(max_length=100)
    kind = models.CharField(max_length=100)
    revision = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["family", "scope", "field", "kind"], name="decision_identity"
            )
        ]


class DecisionEvent(Record):
    decision = models.ForeignKey(Decision, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    value = models.JSONField()
    rationale = models.TextField()
    evidence = models.JSONField(default=list)
    resolver_revision = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["decision", "revision"], name="decision_revision")
        ]


class PublicationGeneration(Record):
    proposal = models.ForeignKey(Proposal, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField()
    state = models.CharField(max_length=20, default="staged")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["proposal", "revision"], name="publication_revision"),
            models.UniqueConstraint(
                fields=["proposal"], condition=Q(state="active"), name="one_active_generation"
            ),
        ]


class PublicationArtifact(Record):
    generation = models.ForeignKey(PublicationGeneration, on_delete=models.PROTECT)
    unit = models.ForeignKey(ExtractedUnit, on_delete=models.PROTECT)
    decision_event = models.ForeignKey(DecisionEvent, on_delete=models.PROTECT)
    blob = models.ForeignKey(ContentBlob, on_delete=models.PROTECT)
    eligible = models.BooleanField(default=False)


class Job(Record):
    collection = models.ForeignKey(Collection, on_delete=models.PROTECT)
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    key = models.CharField(max_length=200)
    kind = models.CharField(max_length=100, default="fixture")
    state = models.CharField(max_length=30, default="queued")
    payload = models.JSONField(default=dict)
    result = models.JSONField(default=dict)
    attempts = models.PositiveIntegerField(default=0)
    lease_token = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    available_at = models.DateTimeField(default=timezone.now)
    stop_reason = models.CharField(max_length=100, blank=True)
    resume_state = models.CharField(max_length=30, blank=True)
    budget = models.DecimalField(max_digits=12, decimal_places=6)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["collection", "key"], name="job_idempotency"),
            models.CheckConstraint(condition=Q(budget__gte=0), name="job_budget_positive"),
        ]
        indexes = [models.Index(fields=["state", "available_at"])]


class Attempt(Record):
    job = models.ForeignKey(Job, on_delete=models.PROTECT)
    number = models.PositiveIntegerField()
    token = models.UUIDField(unique=True)
    state = models.CharField(max_length=30, default="claimed")
    finished_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["job", "number"], name="job_attempt")]


class BudgetAccount(models.Model):
    """Global limits cannot be bypassed by creating another collection/job."""

    key = models.CharField(max_length=30, primary_key=True)
    limit = models.DecimalField(max_digits=12, decimal_places=6)
    committed = models.DecimalField(max_digits=12, decimal_places=6, default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(limit__gte=0) & Q(committed__gte=0), name="budget_nonnegative"
            )
        ]


class UsageReservation(Record):
    attempt = models.OneToOneField(Attempt, on_delete=models.PROTECT)
    accounts = models.ManyToManyField(BudgetAccount)
    reserved = models.DecimalField(max_digits=12, decimal_places=6)
    charged = models.DecimalField(max_digits=12, decimal_places=6)
    actual = models.DecimalField(max_digits=12, decimal_places=6, null=True)
    state = models.CharField(max_length=30, default="reserved")
    usage = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(reserved__gte=0)
                & Q(charged__gte=0)
                & (Q(actual__isnull=True) | Q(actual__gte=0)),
                name="usage_nonnegative",
            )
        ]


class Outbox(Record):
    job = models.OneToOneField(Job, on_delete=models.PROTECT)
    delivered_at = models.DateTimeField(null=True)


class JobResult(Record):
    job = models.OneToOneField(Job, on_delete=models.PROTECT)
    value = models.JSONField()


class DraftSession(Record):
    collection = models.ForeignKey(Collection, on_delete=models.PROTECT)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    title = models.CharField(max_length=200)
    revision = models.PositiveIntegerField(default=0)
    deleted_at = models.DateTimeField(null=True)


class EvidencePacket(Record):
    session = models.ForeignKey(DraftSession, on_delete=models.PROTECT)
    payload = models.JSONField(default=list)
    policy_revision = models.CharField(max_length=100)


class DraftRevision(Record):
    session = models.ForeignKey(DraftSession, on_delete=models.PROTECT)
    number = models.PositiveIntegerField()
    packet = models.ForeignKey(EvidencePacket, on_delete=models.PROTECT)
    text = models.TextField()
    model_revision = models.CharField(max_length=100, blank=True)
    prompt_revision = models.CharField(max_length=100, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["session", "number"], name="draft_revision")]


class DraftExport(Record):
    revision = models.ForeignKey(DraftRevision, on_delete=models.PROTECT)
    text = models.TextField()


class EvaluationRun(Record):
    collection = models.ForeignKey(Collection, on_delete=models.PROTECT)
    suite_revision = models.CharField(max_length=100)
    settings = models.JSONField(default=dict)


class EvaluationRecord(Record):
    run = models.ForeignKey(EvaluationRun, on_delete=models.PROTECT)
    case = models.CharField(max_length=200)
    result = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["run", "case"], name="evaluation_case")]


class AuditRecord(Record):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True)
    action = models.CharField(max_length=100)
    object_id = models.UUIDField()
    details = models.JSONField(default=dict)


class LegacyImport(Record):
    collection = models.ForeignKey(Collection, on_delete=models.PROTECT)
    sha256 = models.CharField(max_length=64)
    records = models.JSONField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["collection", "sha256"], name="legacy_import_once")
        ]
