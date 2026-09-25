"""Scoped, auditable classification and passage treatment for MVP-05.

Recommendations never grant publication permission. Human decisions and the
collection's explicit prohibitions are applied by this service, not by a model.
"""

import hashlib
import json
import re
import uuid

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import Http404

from . import models as m, services

DIMENSIONS = {
    "source_role",
    "authorship",
    "version_status",
    "content_use",
    "claim_type",
    "chemistry",
    "conditions",
    "temporal_meaning",
    "treatment",
    "sensitivity",
}
ENUMS = {
    "authorship": {"ours", "partner", "external", "unknown"},
    "version_status": {"submitted", "final", "draft", "superseded", "unknown"},
    "content_use": {"factual", "voice", "requirements", "context", "administrative", "unknown"},
    "claim_type": {
        "measurement",
        "model",
        "target",
        "hypothesis",
        "requirement",
        "none",
        "unknown",
    },
    "temporal_meaning": {"historical", "current_target", "current_measurement", "unknown"},
    "treatment": {"full", "partial", "summary", "metadata_only", "excluded", "unknown"},
    "sensitivity": {"none", "financial_sensitive", "personal_sensitive", "unknown"},
}
SCOPE_RANK = {"family": 1, "entity": 2, "version": 2, "section": 3, "unit": 4}
RESOLVING_ACTIONS = {"approve", "edit", "automatic"}
UNRESOLVED_STATES = {"unresolved", "deferred", "conflict"}


def _hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def config_fingerprint():
    """Publication-sensitive model and policy configuration for current plans."""
    app = settings.APP
    return _hash(
        [
            app["classification_routes"],
            app["classification_task_routes"],
            app["classification_model_revision"],
            app["classification_prompt_revision"],
            app["classification_schema_revision"],
            app["classification_auto_policy_revision"],
            app["classification_max_excerpt_chars"],
            app["classification_max_output_tokens"],
            app["classification_numeric_entity_terms"],
            app["curation_policy_revision"],
            app["curation_prohibited_sensitivity"],
            app["curation_max_evidence_units"],
            app["curation_max_summary_chars"],
            app["curation_max_reconcile_versions"],
            app["curation_max_reconcile_facts"],
        ]
    )


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise ValueError("Scope identity must be a UUID") from None


def _member(family, version):
    return m.ProposalMembership.objects.filter(source=version.source, family=family).exists()


def _scope(family, scope):
    """Validate the semantic entity so a string cannot escape its family."""
    parts = scope.split(":", 2)
    kind = parts[0]
    if kind not in SCOPE_RANK or len(parts) < 2:
        raise ValueError("Unsupported decision scope")
    if kind == "family":
        if len(parts) != 2 or _uuid(parts[1]) != family.id:
            raise ValueError("Family scope does not match decision family")
        return kind, None, None
    if kind == "entity":
        if len(parts) != 2 or not re.fullmatch(r"[a-z0-9_-]{1,100}", parts[1]):
            raise ValueError("Malformed semantic entity scope")
        if not m.ClassificationFact.objects.filter(
            family=family, entity_key=parts[1], unit__isnull=False
        ).exists():
            raise ValueError("Semantic entity has no source-backed family fact")
        return kind, None, parts[1]
    if kind == "version":
        if len(parts) != 2:
            raise ValueError("Malformed version scope")
        version = (
            m.SourceVersion.objects.filter(pk=_uuid(parts[1])).select_related("source").first()
        )
        if version is None or not _member(family, version):
            raise ValueError("Version does not belong to decision family")
        return kind, version, None
    if kind == "unit":
        if len(parts) != 2:
            raise ValueError("Malformed unit scope")
        unit = (
            m.ExtractedUnit.objects.select_related("version__source")
            .filter(pk=_uuid(parts[1]))
            .first()
        )
        if unit is None or not _member(family, unit.version):
            raise ValueError("Unit does not belong to decision family")
        return kind, unit.version, unit
    if len(parts) != 3 or not parts[2] or len(parts[2]) > 100:
        raise ValueError("Malformed section scope")
    version = m.SourceVersion.objects.filter(pk=_uuid(parts[1])).select_related("source").first()
    if version is None or not _member(family, version):
        raise ValueError("Section version does not belong to decision family")
    return kind, version, parts[2]


def _validate_dimension(dimension, value):
    if dimension not in DIMENSIONS:
        raise ValueError("Unsupported classification dimension")
    if dimension in ENUMS and (not isinstance(value, str) or value not in ENUMS[dimension]):
        raise ValueError("Invalid bounded classification value")
    if (
        dimension in {"chemistry", "source_role"}
        and value is not None
        and (not isinstance(value, str) or len(value) > 200)
    ):
        raise ValueError("Classification text must be short or unknown")
    if (
        dimension == "conditions"
        and value is not None
        and (not isinstance(value, dict) or len(json.dumps(value)) > 2000)
    ):
        raise ValueError("Conditions must be a bounded mapping or unknown")


@transaction.atomic
def record_fact(
    user,
    family_id,
    version_id,
    dimension,
    value,
    *,
    unit_id=None,
    rationale,
    evidence,
    origin,
    resolver_revision,
    entity_key="",
):
    family = (
        m.VersionFamily.objects.select_for_update().select_related("proposal").get(pk=family_id)
    )
    services.authorize(user, family.proposal.collection_id)
    version = m.SourceVersion.objects.select_related("source").get(pk=version_id)
    if not _member(family, version):
        raise ValueError("Version does not belong to family")
    if origin not in {"rule", "model", "human", "policy"} or not resolver_revision:
        raise ValueError("Classification provenance is required")
    _validate_dimension(dimension, value)
    if entity_key and not re.fullmatch(r"[a-z0-9_-]{1,100}", entity_key):
        raise ValueError("Semantic entity key must be stable and bounded")
    if not rationale.strip():
        raise ValueError("Classification rationale is required")
    unit = m.ExtractedUnit.objects.filter(pk=unit_id, version=version).first() if unit_id else None
    if unit_id and unit is None:
        raise ValueError("Evidence unit does not belong to version")
    evidence = _validate_evidence(family, evidence)
    payload = [
        str(family.id),
        str(version.id),
        str(unit.id) if unit else None,
        dimension,
        entity_key,
        value,
        rationale,
        evidence,
        origin,
        resolver_revision,
    ]
    fingerprint = _hash(payload)
    fact, created = m.ClassificationFact.objects.get_or_create(
        family=family,
        version=version,
        unit=unit,
        dimension=dimension,
        fingerprint=fingerprint,
        defaults={
            "value": value,
            "entity_key": entity_key,
            "rationale": rationale,
            "evidence": evidence,
            "origin": origin,
            "resolver_revision": resolver_revision,
        },
    )
    if created:
        m.CurationPlan.objects.filter(family=family, version=version, state="current").update(
            state="invalidated"
        )
        artifacts = m.PublicationArtifact.objects.filter(
            generation__proposal=family.proposal, unit__version=version, eligible=True
        )
        if unit:
            artifacts = artifacts.filter(unit=unit)
        artifacts.update(eligible=False)
    return fact


def deterministic_facts(user, family_id, version_id):
    """Only extract evidence-grounded facts; names establish neither status nor authorship."""
    units = m.ExtractedUnit.objects.filter(version_id=version_id, extraction_run__active=True)
    facts = []
    for unit in units:
        if unit.support_kind == "voice":
            fact = record_fact(
                user,
                family_id,
                version_id,
                "content_use",
                "voice",
                unit_id=unit.id,
                rationale="The extracted unit is explicitly marked voice-only.",
                evidence=[str(unit.id)],
                origin="rule",
                resolver_revision="curation-rules-v1",
            )
            facts.append(fact)
            issue = recommend(
                user,
                family_id,
                f"unit:{unit.id}",
                "content_use",
                "curation",
                value={"value": "voice"},
                rationale=fact.rationale,
                evidence=[str(unit.id)],
                affected_units=[str(unit.id)],
            )
            if issue.revision == 0 and issue.status == "unresolved":
                automatic_resolution(
                    user,
                    issue.id,
                    0,
                    value={"value": "voice"},
                    rationale=fact.rationale,
                    evidence=[str(unit.id)],
                    resolver_revision="curation-rules-v1",
                )
    return facts


def reconcile_family(user, family_id):
    """Compare bounded facts about the same semantic entity across versions."""
    family = m.VersionFamily.objects.select_related("proposal").get(pk=family_id)
    services.authorize(user, family.proposal.collection_id)
    version_ids = list(
        m.SourceVersion.objects.filter(source__proposalmembership__family=family)
        .order_by("-observed_at", "id")
        .values_list("id", flat=True)
        .distinct()[: settings.APP["curation_max_reconcile_versions"]]
    )
    facts = list(
        m.ClassificationFact.objects.filter(
            family=family,
            version_id__in=version_ids,
            unit__isnull=False,
            dimension__in=["claim_type", "chemistry", "conditions", "temporal_meaning"],
        )
        .exclude(entity_key="")
        .order_by("-created_at", "id")[: settings.APP["curation_max_reconcile_facts"]]
    )
    groups = {}
    for fact in facts:
        groups.setdefault((fact.entity_key, fact.dimension), []).append(fact)
    issues = []
    for (entity_key, dimension), candidates in groups.items():
        values = {_hash(fact.value) for fact in candidates if fact.value not in (None, "unknown")}
        if len(values) < 2:
            continue
        units = sorted({str(fact.unit_id) for fact in candidates})
        recommendation = {"value": "unknown" if dimension in ENUMS else None}
        issues.append(
            recommend(
                user,
                family.id,
                f"entity:{entity_key}",
                dimension,
                "curation",
                value=recommendation,
                rationale="Contradictory source-checked facts for the same semantic entity; inspect versions and conditions.",
                evidence=units,
                affected_units=units,
                critical=True,
            )
        )
    return issues


def _validate_evidence(family, evidence):
    if (
        not isinstance(evidence, list)
        or len(evidence) > settings.APP["curation_max_evidence_units"]
    ):
        raise ValueError("Evidence must be a bounded list of unit IDs")
    ids = [str(_uuid(item)) for item in evidence]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate evidence unit")
    actual = (
        m.ExtractedUnit.objects.filter(
            id__in=ids, version__source__proposalmembership__family=family
        )
        .distinct()
        .count()
    )
    if actual != len(ids):
        raise ValueError("Evidence does not belong to family")
    return ids


def _validate_value(field, value, family):
    if not isinstance(value, dict):
        raise ValueError("Decision value must be typed")
    if field in DIMENSIONS - {"treatment"}:
        if set(value) != {"value"}:
            raise ValueError("Classification decision needs one value")
        _validate_dimension(field, value["value"])
    elif field == "treatment":
        treatment = value.get("treatment")
        _validate_dimension("treatment", treatment)
        if treatment == "partial":
            if set(value) != {"treatment", "selected_units"}:
                raise ValueError("Partial treatment has unexpected fields")
            selected = _validate_evidence(family, value.get("selected_units"))
            if not selected:
                raise ValueError("Partial treatment needs selected units")
            value["selected_units"] = selected
        elif treatment == "summary":
            if set(value) != {"treatment", "source_units", "summary", "voice_eligible"}:
                raise ValueError("Summary treatment has unexpected fields")
            sources = _validate_evidence(family, value.get("source_units"))
            if (
                not sources
                or not isinstance(value.get("summary"), str)
                or not value["summary"].strip()
            ):
                raise ValueError("Summary needs source units and text")
            if len(value["summary"]) > settings.APP["curation_max_summary_chars"]:
                raise ValueError("Summary exceeds the configured limit")
            if value.get("voice_eligible") is not False:
                raise ValueError("Derived summaries cannot be voice examples")
            value["source_units"] = sources
        elif set(value) != {"treatment"}:
            raise ValueError("Treatment has unexpected fields")
    elif field == "voice_approval":
        if set(value) != {"approved"} or not isinstance(value["approved"], bool):
            raise ValueError("Voice approval must be explicit and Boolean")
    else:
        raise ValueError("Unsupported decision field")


def _validate_value_scope(decision, value):
    if decision.field != "treatment":
        return
    ids = value.get("selected_units", value.get("source_units", []))
    for unit in m.ExtractedUnit.objects.select_related("version__source").filter(id__in=ids):
        if not _applies(decision, unit.version, unit):
            raise ValueError("Selected passage is outside decision scope")


def _material(family, value, evidence, affected_units):
    units = m.ExtractedUnit.objects.filter(id__in=evidence).values_list("id", "text")
    source_hashes = sorted(
        (str(unit_id), hashlib.sha256(text.encode()).hexdigest()) for unit_id, text in units
    )
    return _hash([str(family.id), value, source_hashes, sorted(affected_units)])


@transaction.atomic
def recommend(
    user,
    family_id,
    scope,
    field,
    kind,
    *,
    value,
    rationale,
    evidence,
    affected_units=None,
    critical=False,
):
    """Upsert an uncapped issue; only contradictory material reopens an answer."""
    family = (
        m.VersionFamily.objects.select_for_update().select_related("proposal").get(pk=family_id)
    )
    services.authorize(user, family.proposal.collection_id)
    _scope(family, scope)
    _validate_value(field, value, family)
    evidence = _validate_evidence(family, evidence)
    affected_units = _validate_evidence(family, affected_units or [])
    if not rationale.strip():
        raise ValueError("Recommendation rationale is required")
    fingerprint = _material(family, value, evidence, affected_units)
    decision, created = m.Decision.objects.select_for_update().get_or_create(
        family=family,
        scope=scope,
        field=field,
        kind=kind,
        defaults={
            "recommendation": value,
            "recommendation_rationale": rationale,
            "recommendation_evidence": evidence,
            "material_fingerprint": fingerprint,
            "affected_units": affected_units,
            "critical": critical,
        },
    )
    _validate_value_scope(decision, value)
    if created:
        _invalidate(decision)
        return decision
    changed = decision.material_fingerprint != fingerprint
    critical_added = critical and not decision.critical
    prior = current_event(decision)
    if changed and decision.status == "resolved" and prior and prior.value != value:
        decision.status = "conflict"
        _append_event(
            decision,
            None,
            "reopen",
            {},
            "Material contradictory evidence requires review",
            evidence,
            "curation-reconciliation-v1",
        )
    decision.recommendation = value
    decision.recommendation_rationale = rationale
    decision.recommendation_evidence = evidence
    decision.material_fingerprint = fingerprint
    decision.affected_units = affected_units
    decision.critical = decision.critical or critical
    decision.save()
    if changed or critical_added:
        _invalidate(decision)
    return decision


def _append_event(
    decision, actor, action, value, rationale, evidence, resolver_revision, review_seconds=None
):
    decision.revision += 1
    event = m.DecisionEvent.objects.create(
        decision=decision,
        revision=decision.revision,
        actor=actor,
        action=action,
        value=value,
        rationale=rationale,
        evidence=evidence,
        resolver_revision=resolver_revision,
        review_seconds=review_seconds,
    )
    decision.save(update_fields=["revision"])
    m.AuditRecord.objects.create(
        actor=actor,
        action="decision." + action,
        object_id=event.id,
        details={"scope": decision.scope},
    )
    return event


def current_event(decision):
    """Replay immutable events, including compensating undo and reopening."""
    return _active_event(m.DecisionEvent.objects.filter(decision=decision).order_by("revision"))


def _active_event(events):
    stack = []
    for event in events:
        if event.action in RESOLVING_ACTIONS or (event.action == "reject" and event.value):
            stack.append(event)
        elif event.action == "undo" and stack:
            stack.pop()
        elif event.action in {"defer", "reopen"}:
            stack.clear()
        elif event.action == "reject":
            stack.clear()
    return stack[-1] if stack else None


def _affected_version_ids(decision):
    kind, version, unit_or_section = _scope(decision.family, decision.scope)
    if version:
        return [version.id]
    if kind == "entity":
        return list(
            m.ClassificationFact.objects.filter(family=decision.family, entity_key=unit_or_section)
            .values_list("version_id", flat=True)
            .distinct()
        )
    return list(
        m.SourceVersion.objects.filter(
            source__proposalmembership__family=decision.family
        ).values_list("id", flat=True)
    )


def _invalidate(decision):
    version_ids = _affected_version_ids(decision)
    plans = m.CurationPlan.objects.filter(
        family=decision.family, version_id__in=version_ids, state="current"
    )
    plans.update(state="invalidated")
    # MVP-02 artifacts are immediately made ineligible; historical citations stay intact.
    artifacts = m.PublicationArtifact.objects.filter(
        generation__proposal=decision.family.proposal,
        unit__version_id__in=version_ids,
        eligible=True,
    )
    if decision.scope.startswith("unit:"):
        artifacts = artifacts.filter(unit_id=decision.scope.removeprefix("unit:"))
    elif decision.scope.startswith("section:"):
        section = decision.scope.split(":", 2)[2]
        artifacts = artifacts.filter(unit__locator__section=section)
    elif decision.scope.startswith("entity:"):
        entity_key = decision.scope.removeprefix("entity:")
        unit_ids = m.ClassificationFact.objects.filter(
            family=decision.family, entity_key=entity_key, unit__isnull=False
        ).values_list("unit_id", flat=True)
        artifacts = artifacts.filter(unit_id__in=unit_ids)
    artifacts.update(eligible=False)


@transaction.atomic
def review(
    user,
    decision_id,
    expected_revision,
    action,
    *,
    value=None,
    rationale="",
    evidence=None,
    review_seconds=None,
):
    family_id = (
        m.Decision.objects.filter(pk=decision_id).values_list("family_id", flat=True).first()
    )
    if family_id is None:
        raise Http404
    m.VersionFamily.objects.select_for_update().get(pk=family_id)
    decision = (
        m.Decision.objects.select_for_update()
        .select_related("family__proposal")
        .filter(pk=decision_id)
        .first()
    )
    if decision is None:
        raise Http404
    services.authorize(user, decision.family.proposal.collection_id)
    _scope(decision.family, decision.scope)
    if decision.revision != expected_revision:
        raise ValueError("Decision changed; refresh before editing")
    if action not in {"approve", "edit", "defer", "reject", "undo"}:
        raise ValueError("Unsupported review action")
    if action == "approve":
        if not decision.recommendation:
            raise ValueError("No recommendation to approve")
        if not decision.recommendation_evidence:
            raise ValueError("Recommendation needs source evidence before approval")
        value = decision.recommendation
        rationale = rationale or "Approved recommendation"
    elif action == "edit" and not rationale.strip():
        raise ValueError("An edit needs a rationale")
    elif action == "reject" and value and not rationale.strip():
        raise ValueError("An alternative needs a rationale")
    elif action in {"defer", "reject"} and not rationale.strip():
        raise ValueError("A deferral or rejection needs a reason")
    if action in {"approve", "edit"} or (action == "reject" and value):
        _validate_value(decision.field, value, decision.family)
        _validate_value_scope(decision, value)
        if decision.field == "voice_approval" and action == "approve":
            raise ValueError("Voice approval requires an explicit human edit")
    elif action == "undo" and current_event(decision) is None:
        raise ValueError("No active answer to undo")
    else:
        value = {}
    evidence = _validate_evidence(
        decision.family, evidence if evidence is not None else decision.recommendation_evidence
    )
    if review_seconds is not None:
        if not isinstance(review_seconds, int) or not 0 <= review_seconds <= 3600:
            raise ValueError("Review duration is outside the allowed range")
    event = _append_event(
        decision,
        user,
        action,
        value,
        rationale,
        evidence,
        "human-curation-v1",
        review_seconds=review_seconds,
    )
    decision.status = {
        "approve": "resolved",
        "edit": "resolved",
        "defer": "deferred",
        "reject": "resolved" if value else "unresolved",
        "undo": "resolved" if current_event(decision) else "unresolved",
    }[action]
    decision.save(update_fields=["status"])
    _invalidate(decision)
    return event


@transaction.atomic
def automatic_resolution(
    user,
    decision_id,
    expected_revision,
    *,
    value,
    rationale,
    evidence,
    resolver_revision,
    allow_treatment=False,
):
    family_id = m.Decision.objects.values_list("family_id", flat=True).get(pk=decision_id)
    m.VersionFamily.objects.select_for_update().get(pk=family_id)
    decision = (
        m.Decision.objects.select_for_update()
        .select_related("family__proposal")
        .get(pk=decision_id)
    )
    services.authorize(user, decision.family.proposal.collection_id)
    if decision.revision != expected_revision or decision.status != "unresolved":
        raise ValueError("Decision already changed or resolved")
    if m.DecisionEvent.objects.filter(decision=decision, actor__isnull=False).exists():
        raise ValueError("Human-reviewed decisions require human resolution")
    _validate_value(decision.field, value, decision.family)
    _validate_value_scope(decision, value)
    if decision.field == "voice_approval" or (
        decision.field == "treatment" and not allow_treatment
    ):
        raise ValueError("Voice approval and passage treatment require human review")
    if decision.field == "treatment":
        result = (
            m.ClassificationResult.objects.filter(
                family=decision.family,
                unit_id=decision.scope.removeprefix("unit:"),
                state="succeeded",
                job__payload__mode="mock",
                policy_revision=resolver_revision,
            )
            .select_related("job", "unit")
            .order_by("-created_at")
            .first()
        )
        from .classification import _current

        predictions = result.predictions if result else {}
        safe = (
            result is not None
            and _current(result.job) is not None
            and predictions.get("treatment", {}).get("value") == "full"
            and predictions.get("content_use", {}).get("value") == "factual"
            and predictions.get("sensitivity", {}).get("value") == "none"
            and predictions.get("claim_type", {}).get("value")
            not in {"measurement", "target", "requirement"}
            and all(
                predictions.get(field, {}).get("confidence") is not None
                for field in ("treatment", "content_use", "sensitivity")
            )
        )
        if (
            value != {"treatment": "full"}
            or not decision.scope.startswith("unit:")
            or resolver_revision != settings.APP["classification_auto_policy_revision"]
            or not safe
        ):
            raise ValueError("Automatic treatment is limited to current-policy unit inclusion")
    evidence = _validate_evidence(decision.family, evidence)
    if not evidence or not rationale.strip() or not resolver_revision:
        raise ValueError("Automatic resolution needs rationale and version")
    event = _append_event(
        decision, None, "automatic", value, rationale, evidence, resolver_revision
    )
    decision.status = "resolved"
    decision.save(update_fields=["status"])
    _invalidate(decision)
    return event


def _applies(decision, version, unit):
    kind, scoped_version, scoped = _scope(decision.family, decision.scope)
    if kind == "family":
        return True
    if kind == "entity":
        return m.ClassificationFact.objects.filter(
            family=decision.family, version=version, unit=unit, entity_key=scoped
        ).exists()
    if scoped_version.id != version.id:
        return False
    if kind == "version":
        return True
    if unit is None:
        return False
    if kind == "unit":
        return scoped.id == unit.id
    return str(unit.locator.get("section", "")) == scoped


def effective_value(family, version, unit, field, kind="curation"):
    """Human answers outrank automation; then narrower applicable scope wins."""
    applicable = []
    for decision in m.Decision.objects.filter(
        family=family, field=field, kind=kind, status="resolved"
    ):
        if not _applies(decision, version, unit):
            continue
        event = current_event(decision)
        if event:
            rank = SCOPE_RANK[decision.scope.split(":", 1)[0]]
            applicable.append((1 if event.actor_id else 0, rank, decision, event))
    if not applicable:
        return None, None
    applicable.sort(key=lambda item: (item[0], item[1]), reverse=True)
    winning = applicable[0]
    if any(
        peer[:2] == winning[:2] and peer[3].value != winning[3].value for peer in applicable[1:]
    ):
        raise ValueError("Conflicting applicable decisions require review")
    return winning[3].value, winning[3]


def review_queue(collection_id, *, limit=None):
    """The full unresolved set is retained even when the initial view is capped."""
    issues = list(
        m.Decision.objects.filter(
            family__proposal__collection_id=collection_id,
            field__in=sorted(DIMENSIONS | {"voice_approval"}),
            status__in=UNRESOLVED_STATES,
        )
        .select_related("family__proposal")
        .order_by("-critical", "created_at")
    )
    limit = settings.APP["curation_review_target"] if limit is None else limit
    return {
        "visible": issues[:limit],
        "all": issues,
        "hidden_count": max(0, len(issues) - limit),
        "critical_count": sum(issue.critical for issue in issues),
    }


def blocking_issues(family, version, unit=None):
    return [
        issue
        for issue in m.Decision.objects.filter(family=family, status__in=UNRESOLVED_STATES).filter(
            Q(critical=True) | Q(status="conflict")
        )
        if _applies(issue, version, unit)
    ]


@transaction.atomic
def build_plan(user, family_id, version_id):
    family = (
        m.VersionFamily.objects.select_for_update().select_related("proposal").get(pk=family_id)
    )
    services.authorize(user, family.proposal.collection_id)
    version = m.SourceVersion.objects.select_related("source").get(pk=version_id)
    if not _member(family, version):
        raise ValueError("Version does not belong to family")
    from .classification import _latest

    if not _latest(version):
        raise ValueError("Only the current source version can be curated")
    run = m.ExtractionRun.objects.filter(version=version, active=True, state="succeeded").first()
    if run is None:
        raise ValueError("A successful active extraction is required")
    units = list(m.ExtractedUnit.objects.filter(extraction_run=run).order_by("ordinal", "key"))
    if not units:
        raise ValueError("No extracted units can be curated")
    # Extracted units are immutable. Use the current classification result for
    # content use instead of rewriting extraction history after a model call.
    from .classification import _current

    support_kinds = {unit.id: unit.support_kind for unit in units}
    for result in m.ClassificationResult.objects.filter(
        family=family, extraction_run=run, state="succeeded"
    ).select_related("job"):
        if _current(result.job) is None:
            continue
        content_use = result.predictions.get("content_use", {}).get("value")
        support_kinds[result.unit_id] = (
            "voice"
            if content_use == "voice"
            else "factual" if content_use == "factual" else "unclassified"
        )
    facts = list(
        m.ClassificationFact.objects.filter(family=family, version=version).values_list(
            "dimension", "value", "unit_id", "entity_key"
        )
    )
    policy = settings.APP["curation_prohibited_sensitivity"]
    prohibited_version = any(
        dimension == "sensitivity" and value in policy and unit_id is None
        for dimension, value, unit_id, _ in facts
    )
    prohibited_units = {
        unit_id
        for dimension, value, unit_id, _ in facts
        if dimension == "sensitivity" and value in policy and unit_id is not None
    }
    entities_by_unit = {}
    for _, _, unit_id, entity_key in facts:
        if unit_id is not None and entity_key:
            entities_by_unit.setdefault(unit_id, set()).add(entity_key)

    source_decisions = list(
        m.Decision.objects.filter(
            family=family, status__in=UNRESOLVED_STATES | {"resolved"}
        ).filter(
            Q(field__in=DIMENSIONS | {"voice_approval"}) | Q(critical=True) | Q(status="conflict")
        )
    )
    events_by_decision = {}
    for item in m.DecisionEvent.objects.filter(
        decision_id__in=[decision.id for decision in source_decisions]
    ).order_by("decision_id", "revision"):
        events_by_decision.setdefault(item.decision_id, []).append(item)
    compiled = [
        (
            decision,
            _scope(family, decision.scope),
            _active_event(events_by_decision.get(decision.id, [])),
        )
        for decision in source_decisions
    ]

    def applies(scope, unit):
        kind, scoped_version, scoped = scope
        if kind == "family":
            return True
        if kind == "entity":
            return scoped in entities_by_unit.get(unit.id, set())
        if scoped_version.id != version.id:
            return False
        if kind == "version":
            return True
        if kind == "unit":
            return scoped.id == unit.id
        return str(unit.locator.get("section", "")) == scoped

    def resolved_value(field, unit):
        applicable = []
        for decision, scope, event in compiled:
            if decision.field != field or decision.status != "resolved" or event is None:
                continue
            if applies(scope, unit):
                rank = SCOPE_RANK[scope[0]]
                applicable.append((1 if event.actor_id else 0, rank, event))
        if not applicable:
            return None, None
        applicable.sort(key=lambda item: (item[0], item[1]), reverse=True)
        winner = applicable[0]
        if any(
            other[:2] == winner[:2] and other[2].value != winner[2].value
            for other in applicable[1:]
        ):
            raise ValueError("Conflicting applicable decisions require review")
        return winner[2].value, winner[2]

    def has_blocker(unit):
        return any(
            applies(scope, unit)
            for decision, scope, _ in compiled
            if decision.status in UNRESOLVED_STATES
            and (decision.critical or decision.status == "conflict")
        )

    eligible, voice, excluded, pending, metadata_units, summaries = [], [], [], [], [], []
    decisions, warnings = {}, []
    for unit in units:
        if prohibited_version or unit.id in prohibited_units:
            excluded.append(str(unit.id))
            warnings.append(f"Policy prohibition: {unit.id}")
            continue
        try:
            value, event = resolved_value("treatment", unit)
        except ValueError as exc:
            conflict = recommend(
                user,
                family.id,
                f"unit:{unit.id}",
                "treatment",
                "curation",
                value={"treatment": "unknown"},
                rationale=str(exc),
                evidence=[str(unit.id)],
                affected_units=[str(unit.id)],
                critical=True,
            )
            conflict.status = "conflict"
            conflict.save(update_fields=["status"])
            pending.append(str(unit.id))
            warnings.append(f"Conflicting scoped decisions: {unit.id}")
            continue
        treatment = (value or {}).get("treatment", "unknown")
        if event:
            decisions[str(event.decision_id)] = event.revision
        if treatment == "excluded" and event and event.actor_id:
            excluded.append(str(unit.id))
            continue
        if has_blocker(unit):
            pending.append(str(unit.id))
            warnings.append(f"Critical review pending: {unit.id}")
            continue
        support_kind = support_kinds[unit.id]
        if support_kind == "voice":
            if treatment == "excluded":
                excluded.append(str(unit.id))
                continue
            if treatment == "metadata_only":
                metadata_units.append(str(unit.id))
                continue
            try:
                approval, approval_event = resolved_value("voice_approval", unit)
            except ValueError as exc:
                conflict = recommend(
                    user,
                    family.id,
                    f"unit:{unit.id}",
                    "voice_approval",
                    "curation",
                    value={"approved": False},
                    rationale=str(exc),
                    evidence=[str(unit.id)],
                    affected_units=[str(unit.id)],
                    critical=True,
                )
                conflict.status = "conflict"
                conflict.save(update_fields=["status"])
                pending.append(str(unit.id))
                warnings.append(f"Conflicting voice decisions: {unit.id}")
                continue
            if approval == {"approved": True} and approval_event.actor_id:
                voice.append(str(unit.id))
            else:
                pending.append(str(unit.id))
            continue
        if treatment == "full" and support_kind == "factual":
            eligible.append(str(unit.id))
        elif (
            treatment == "partial"
            and str(unit.id) in value["selected_units"]
            and support_kind == "factual"
        ):
            eligible.append(str(unit.id))
        elif treatment == "summary" and str(unit.id) in value["source_units"]:
            summary = {
                "text": value["summary"],
                "source_units": value["source_units"],
                "support_kind": "derived",
                "voice_eligible": False,
                "decision_event_id": str(event.id),
            }
            if summary not in summaries:
                summaries.append(summary)
            excluded.append(str(unit.id))
        elif treatment == "metadata_only":
            metadata_units.append(str(unit.id))
        elif treatment == "unknown":
            pending.append(str(unit.id))
            warnings.append(f"No treatment decision: {unit.id}")
        else:
            excluded.append(str(unit.id))
    metadata_only = bool(metadata_units) and not (eligible or voice or summaries or pending)
    fingerprint = _hash(
        [
            str(family.id),
            str(version.id),
            str(run.id),
            eligible,
            voice,
            excluded,
            pending,
            metadata_units,
            summaries,
            decisions,
            warnings,
            settings.APP["curation_policy_revision"],
            settings.APP["classification_auto_policy_revision"],
            config_fingerprint(),
        ]
    )
    m.CurationPlan.objects.filter(family=family, version=version, state="current").exclude(
        fingerprint=fingerprint
    ).update(state="superseded")
    plan, _ = m.CurationPlan.objects.update_or_create(
        family=family,
        version=version,
        fingerprint=fingerprint,
        defaults={
            "extraction_run": run,
            "config_fingerprint": config_fingerprint(),
            "state": "current",
            "eligible_units": eligible,
            "voice_units": voice,
            "excluded_units": excluded,
            "pending_units": pending,
            "metadata_only_units": metadata_units,
            "derived_summaries": summaries,
            "metadata_only": metadata_only,
            "decision_revisions": decisions,
            "warnings": warnings,
        },
    )
    return plan
