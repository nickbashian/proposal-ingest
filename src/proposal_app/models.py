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
    disposition = models.CharField(max_length=30, default="awaiting_decision")
    disposition_reason = models.CharField(max_length=300, blank=True)

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
    observed_path = models.TextField(blank=True)

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


class SourceScope(Record):
    """One configured proposal/year subtree, never a tenant-wide crawl."""

    collection = models.ForeignKey(Collection, on_delete=models.PROTECT)
    connector = models.CharField(max_length=80)
    tenant = models.CharField(max_length=200)
    site = models.CharField(max_length=200)
    drive = models.CharField(max_length=200)
    root_item = models.CharField(max_length=500)
    proposal = models.ForeignKey(Proposal, on_delete=models.PROTECT)
    year = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "collection",
                    "connector",
                    "tenant",
                    "site",
                    "drive",
                    "root_item",
                    "proposal",
                ],
                name="source_scope_identity",
            )
        ]


class SourceSyncRun(Record):
    scope = models.ForeignKey(SourceScope, on_delete=models.PROTECT)
    state = models.CharField(max_length=30, default="running")
    cursor = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=100, blank=True)
    counts = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["scope"], condition=Q(state="running"), name="one_running_source_sync"
            )
        ]


class SourcePresence(Record):
    scope = models.ForeignKey(SourceScope, on_delete=models.PROTECT)
    source = models.ForeignKey(SourceItem, on_delete=models.PROTECT)
    last_seen_run = models.ForeignKey(SourceSyncRun, on_delete=models.PROTECT)
    observed_at = models.DateTimeField(default=timezone.now)
    display_path = models.TextField()
    retired_at = models.DateTimeField(null=True)
    disposition = models.CharField(max_length=40)
    reason = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["scope", "source"], name="scope_source_presence")
        ]


class SourceCaptureIssue(Record):
    run = models.ForeignKey(SourceSyncRun, on_delete=models.PROTECT)
    source_item = models.CharField(max_length=500)
    code = models.CharField(max_length=100)
    observed_at = models.DateTimeField(default=timezone.now)


class SourcePathEvent(Record):
    run = models.ForeignKey(SourceSyncRun, on_delete=models.PROTECT)
    source = models.ForeignKey(SourceItem, on_delete=models.PROTECT)
    scope = models.ForeignKey(SourceScope, on_delete=models.PROTECT)
    display_path = models.TextField()


class ExtractedUnit(Record):
    version = models.ForeignKey(SourceVersion, on_delete=models.PROTECT)
    extractor_revision = models.CharField(max_length=100)
    key = models.CharField(max_length=200)
    locator = models.JSONField()
    text = models.TextField()
    support_kind = models.CharField(max_length=30, default="factual")
    extraction_run = models.ForeignKey("ExtractionRun", on_delete=models.PROTECT, null=True)
    kind = models.CharField(max_length=40, default="paragraph")
    context = models.JSONField(default=dict)
    warnings = models.JSONField(default=list)
    ordinal = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["version", "extractor_revision", "key"], name="version_locator"
            )
        ]


class ExtractionRun(Record):
    """Immutable attempt and cache identity for one source version."""

    version = models.ForeignKey(SourceVersion, on_delete=models.PROTECT)
    number = models.PositiveIntegerField()
    fingerprint = models.CharField(max_length=64)
    extractor_revision = models.CharField(max_length=100)
    parser = models.CharField(max_length=100)
    state = models.CharField(max_length=30)
    reason = models.CharField(max_length=100, blank=True)
    recovery_action = models.CharField(max_length=300, blank=True)
    warnings = models.JSONField(default=list)
    active = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["version", "number"], name="extraction_run_number"),
            models.UniqueConstraint(
                fields=["version"], condition=Q(active=True), name="one_active_extraction"
            ),
        ]


class FigureAsset(Record):
    run = models.ForeignKey(ExtractionRun, on_delete=models.PROTECT)
    key = models.CharField(max_length=200)
    locator = models.JSONField()
    blob = models.ForeignKey(ContentBlob, on_delete=models.PROTECT)
    mime_type = models.CharField(max_length=50)
    caption = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["run", "key"], name="run_figure_key")]


class VisualInspection(Record):
    """A selective manual/OCR interpretation, never an original source fact."""

    run = models.ForeignKey(ExtractionRun, on_delete=models.PROTECT)
    figure = models.ForeignKey(FigureAsset, on_delete=models.PROTECT, null=True)
    locator = models.JSONField()
    kind = models.CharField(max_length=20)
    state = models.CharField(max_length=30, default="requested")
    interpretation = models.TextField(blank=True)
    source_check = models.TextField(blank=True)
    adapter_revision = models.CharField(max_length=100, default="manual-v1")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "figure", "kind"],
                condition=Q(figure__isnull=False),
                name="one_visual_request_per_figure",
            )
        ]


class Decision(Record):
    family = models.ForeignKey(VersionFamily, on_delete=models.PROTECT)
    scope = models.CharField(max_length=200)
    field = models.CharField(max_length=100)
    kind = models.CharField(max_length=100)
    revision = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=30, default="unresolved")
    critical = models.BooleanField(default=False)
    recommendation = models.JSONField(default=dict)
    recommendation_rationale = models.TextField(blank=True)
    recommendation_evidence = models.JSONField(default=list)
    material_fingerprint = models.CharField(max_length=64, blank=True)
    affected_units = models.JSONField(default=list)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["family", "scope", "field", "kind"], name="decision_identity"
            )
        ]


class DecisionEvent(Record):
    decision = models.ForeignKey(Decision, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True)
    action = models.CharField(max_length=30, default="edit")
    value = models.JSONField()
    rationale = models.TextField()
    evidence = models.JSONField(default=list)
    resolver_revision = models.CharField(max_length=100)
    review_seconds = models.PositiveIntegerField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["decision", "revision"], name="decision_revision")
        ]


class ClassificationFact(Record):
    """One independent bounded dimension for a source version or passage."""

    family = models.ForeignKey(VersionFamily, on_delete=models.PROTECT)
    version = models.ForeignKey(SourceVersion, on_delete=models.PROTECT)
    unit = models.ForeignKey(ExtractedUnit, on_delete=models.PROTECT, null=True)
    dimension = models.CharField(max_length=40)
    entity_key = models.CharField(max_length=100, blank=True)
    value = models.JSONField(null=True)
    rationale = models.TextField()
    evidence = models.JSONField(default=list)
    resolver_revision = models.CharField(max_length=100)
    origin = models.CharField(max_length=20)
    fingerprint = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["family", "version", "unit", "dimension", "fingerprint"],
                condition=Q(unit__isnull=False),
                name="classification_unit_fingerprint",
            ),
            models.UniqueConstraint(
                fields=["family", "version", "dimension", "fingerprint"],
                condition=Q(unit__isnull=True),
                name="classification_version_fingerprint",
            ),
        ]


class ClassificationResult(Record):
    """One validated operational prediction, including abstentions and failures."""

    job = models.OneToOneField("Job", on_delete=models.PROTECT)
    family = models.ForeignKey(VersionFamily, on_delete=models.PROTECT)
    version = models.ForeignKey(SourceVersion, on_delete=models.PROTECT)
    extraction_run = models.ForeignKey(ExtractionRun, on_delete=models.PROTECT)
    unit = models.ForeignKey(ExtractedUnit, on_delete=models.PROTECT)
    fingerprint = models.CharField(max_length=64)
    state = models.CharField(max_length=30)
    predictions = models.JSONField(default=dict)
    error = models.CharField(max_length=100, blank=True)
    model_revision = models.CharField(max_length=100)
    prompt_revision = models.CharField(max_length=100)
    schema_revision = models.CharField(max_length=100)
    policy_revision = models.CharField(max_length=100)
    usage = models.JSONField(default=dict)


class CurationPlan(Record):
    """A versioned eligibility plan; MVP-06 will render its approved bytes."""

    family = models.ForeignKey(VersionFamily, on_delete=models.PROTECT)
    version = models.ForeignKey(SourceVersion, on_delete=models.PROTECT)
    extraction_run = models.ForeignKey(ExtractionRun, on_delete=models.PROTECT, null=True)
    fingerprint = models.CharField(max_length=64)
    config_fingerprint = models.CharField(max_length=64, blank=True)
    state = models.CharField(max_length=20, default="current")
    eligible_units = models.JSONField(default=list)
    voice_units = models.JSONField(default=list)
    excluded_units = models.JSONField(default=list)
    pending_units = models.JSONField(default=list)
    metadata_only_units = models.JSONField(default=list)
    derived_summaries = models.JSONField(default=list)
    metadata_only = models.BooleanField(default=False)
    decision_revisions = models.JSONField(default=dict)
    warnings = models.JSONField(default=list)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["family", "version", "fingerprint"], name="curation_plan_identity"
            ),
            models.UniqueConstraint(
                fields=["family", "version"],
                condition=Q(state="current"),
                name="one_current_curation_plan",
            ),
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
    """Curated bytes have their own blob; units reference the original source version."""

    generation = models.ForeignKey(PublicationGeneration, on_delete=models.PROTECT)
    unit = models.ForeignKey(ExtractedUnit, on_delete=models.PROTECT)
    decision_event = models.ForeignKey(DecisionEvent, on_delete=models.PROTECT)
    blob = models.ForeignKey(ContentBlob, on_delete=models.PROTECT)
    eligible = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["generation", "unit"], name="generation_unit_artifact")
        ]


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


class EvidencePin(Record):
    session = models.ForeignKey(DraftSession, on_delete=models.PROTECT)
    artifact = models.ForeignKey(PublicationArtifact, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["session", "artifact"], name="session_artifact_pin")
        ]


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


class EvaluationCall(Record):
    """Durable gross reservation before each paid comparison request."""

    run = models.ForeignKey(EvaluationRun, on_delete=models.PROTECT)
    route = models.CharField(max_length=30)
    case = models.CharField(max_length=200)
    state = models.CharField(max_length=30, default="reserved")
    reserved_usd = models.DecimalField(max_digits=12, decimal_places=6)
    model_revision = models.CharField(max_length=100, blank=True)
    error = models.CharField(max_length=100, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "route", "case"], name="evaluation_call_identity"
            )
        ]


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
