"""MVP-05 semantic scope, review, curation plans, and model route contracts."""

import copy
import hashlib
import io
import json
import os
from decimal import Decimal

import pytest
from playwright.sync_api import sync_playwright
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from proposal_app import curation, model_evaluation as evaluation, models as m
from scripts import dev

pytestmark = pytest.mark.django_db


@pytest.fixture
def corpus(settings):
    user = get_user_model().objects.create_user(username="mvp05-owner")
    m.Identity.objects.create(user=user, issuer="local", subject="mvp05-owner", allowed=True)
    collection = m.Collection.objects.create(name="Synthetic curation")
    m.CollectionAccess.objects.create(user=user, collection=collection)
    proposal = m.Proposal.objects.create(collection=collection, identifier="P-1")
    families = [
        m.VersionFamily.objects.create(proposal=proposal, key=key) for key in ("alpha", "beta")
    ]

    def add(family, label, *, support_kinds=("factual", "factual")):
        source = m.SourceItem.objects.create(
            collection=collection,
            connector="local",
            tenant="test",
            site="test",
            drive="test",
            item=label,
            display_path=f"2025/{label}-final.txt",
        )
        m.ProposalMembership.objects.create(source=source, family=family)
        blob = m.ContentBlob.objects.create(
            sha256=hashlib.sha256(label.encode()).hexdigest(), size=1
        )
        version = m.SourceVersion.objects.create(source=source, observation_key="v1", blob=blob)
        run = m.ExtractionRun.objects.create(
            version=version,
            number=1,
            fingerprint="a" * 64,
            extractor_revision="test-v1",
            parser="synthetic",
            state="succeeded",
            active=True,
        )
        units = [
            m.ExtractedUnit.objects.create(
                version=version,
                extraction_run=run,
                extractor_revision="test-v1",
                key=f"{label}-{index}",
                locator={"section": "Approach", "paragraph": index},
                text=f"Synthetic {label} evidence {index}",
                support_kind=kind,
                ordinal=index,
            )
            for index, kind in enumerate(support_kinds)
        ]
        return version, units

    return user, collection, families, add


def issue(
    user,
    family,
    version,
    unit,
    *,
    field="treatment",
    value=None,
    scope=None,
    kind="curation",
    critical=False,
):
    return curation.recommend(
        user,
        family.id,
        scope or f"version:{version.id}",
        field,
        kind,
        value=value or {"treatment": "full"},
        rationale="Source checked synthetic recommendation",
        evidence=[str(unit.id)],
        affected_units=[str(unit.id)],
        critical=critical,
    )


def test_independent_dimensions_unknown_and_filename_cannot_establish_status(corpus):
    user, _, families, add = corpus
    version, units = add(families[0], "looks-submitted")
    assert curation.deterministic_facts(user, families[0].id, version.id) == []
    assert not m.ClassificationFact.objects.filter(
        dimension__in=["authorship", "version_status"]
    ).exists()
    for dimension, value in [
        ("source_role", "technical"),
        ("authorship", "unknown"),
        ("version_status", "unknown"),
        ("content_use", "factual"),
        ("claim_type", "target"),
        ("chemistry", None),
        ("conditions", None),
        ("temporal_meaning", "historical"),
        ("treatment", "unknown"),
    ]:
        curation.record_fact(
            user,
            families[0].id,
            version.id,
            dimension,
            value,
            unit_id=units[0].id,
            rationale="Explicit synthetic source check",
            evidence=[str(units[0].id)],
            origin="human",
            resolver_revision="test-v1",
        )
    assert m.ClassificationFact.objects.filter(version=version).count() == 9
    assert m.ClassificationFact.objects.get(dimension="conditions").value is None


def test_family_identity_human_precedence_narrower_scope_and_undo(corpus):
    user, _, families, add = corpus
    version_a, units_a = add(families[0], "alpha")
    version_b, units_b = add(families[1], "beta")
    broad = issue(
        user,
        families[0],
        version_a,
        units_a[0],
        scope=f"family:{families[0].id}",
        field="content_use",
        value={"value": "factual"},
    )
    curation.automatic_resolution(
        user,
        broad.id,
        0,
        value={"value": "factual"},
        rationale="Deterministic source marker",
        evidence=[str(units_a[0].id)],
        resolver_revision="rule-v1",
    )
    narrow = issue(
        user,
        families[0],
        version_a,
        units_a[0],
        scope=f"unit:{units_a[0].id}",
        field="content_use",
        value={"value": "voice"},
    )
    curation.review(
        user,
        narrow.id,
        0,
        "edit",
        value={"value": "administrative"},
        rationale="Human reviewed exact passage",
    )
    assert curation.effective_value(families[0], version_a, units_a[0], "content_use")[0] == {
        "value": "administrative"
    }
    curation.review(user, narrow.id, 1, "undo")
    assert curation.effective_value(families[0], version_a, units_a[0], "content_use")[0] == {
        "value": "factual"
    }
    other = issue(
        user,
        families[1],
        version_b,
        units_b[0],
        scope=f"family:{families[1].id}",
        field="content_use",
        value={"value": "factual"},
    )
    assert other.id != broad.id
    assert curation.effective_value(families[1], version_b, units_b[0], "content_use")[0] is None
    assert [
        event.action
        for event in m.DecisionEvent.objects.filter(decision=narrow).order_by("revision")
    ] == ["edit", "undo"]
    curation.review(
        user,
        broad.id,
        1,
        "edit",
        value={"value": "administrative"},
        rationale="Human family decision",
    )
    automatic_narrow = issue(
        user,
        families[0],
        version_a,
        units_a[1],
        scope=f"unit:{units_a[1].id}",
        field="content_use",
        value={"value": "voice"},
    )
    curation.automatic_resolution(
        user,
        automatic_narrow.id,
        0,
        value={"value": "voice"},
        rationale="Rule candidate",
        evidence=[str(units_a[1].id)],
        resolver_revision="rule-v1",
    )
    assert curation.effective_value(families[0], version_a, units_a[1], "content_use")[0] == {
        "value": "administrative"
    }


def test_rejection_deferral_revision_conflict_and_material_reopening(corpus):
    user, _, families, add = corpus
    version, units = add(families[0], "review")
    decision = issue(user, families[0], version, units[0], critical=True)
    curation.review(user, decision.id, 0, "reject", rationale="No source support")
    decision.refresh_from_db()
    assert decision.status == "unresolved"
    curation.review(user, decision.id, 1, "defer", rationale="Need source check")
    decision.refresh_from_db()
    assert decision.status == "deferred"
    with pytest.raises(ValueError, match="refresh"):
        curation.review(user, decision.id, 1, "approve")
    curation.review(user, decision.id, 2, "approve")
    same = curation.recommend(
        user,
        families[0].id,
        decision.scope,
        "treatment",
        "curation",
        value={"treatment": "full"},
        rationale="Different wording and run ID",
        evidence=[str(units[0].id)],
        affected_units=[str(units[0].id)],
        critical=True,
    )
    assert same.status == "resolved"
    reopened = curation.recommend(
        user,
        families[0].id,
        decision.scope,
        "treatment",
        "curation",
        value={"treatment": "excluded"},
        rationale="Contradictory source evidence",
        evidence=[str(units[1].id)],
        affected_units=[str(units[0].id)],
        critical=True,
    )
    assert reopened.status == "conflict"
    assert m.DecisionEvent.objects.filter(decision=decision, action="approve").exists()
    assert curation.effective_value(families[0], version, units[0], "treatment")[0] is None


def test_equal_rank_human_conflict_becomes_visible_unit_issue(corpus):
    user, _, families, add = corpus
    version, units = add(families[0], "overlap")
    curation.record_fact(
        user,
        families[0].id,
        version.id,
        "claim_type",
        "target",
        unit_id=units[0].id,
        entity_key="capacity",
        rationale="Synthetic identity",
        evidence=[str(units[0].id)],
        origin="human",
        resolver_revision="test-v1",
    )
    entity = issue(
        user, families[0], version, units[0], scope="entity:capacity", value={"treatment": "full"}
    )
    version_default = issue(user, families[0], version, units[0], value={"treatment": "excluded"})
    curation.review(user, entity.id, 0, "approve")
    curation.review(user, version_default.id, 0, "approve")
    plan = curation.build_plan(user, families[0].id, version.id)
    assert str(units[0].id) in plan.pending_units
    conflict = m.Decision.objects.get(
        family=families[0], scope=f"unit:{units[0].id}", field="treatment", kind="curation"
    )
    assert conflict.status == "conflict" and conflict.critical
    curation.review(
        user,
        conflict.id,
        0,
        "edit",
        value={"treatment": "full"},
        rationale="Resolved using exact passage evidence",
    )
    assert str(units[0].id) in curation.build_plan(user, families[0].id, version.id).eligible_units


def test_partial_policy_voice_and_summary_plans_are_machine_enforceable(corpus):
    user, _, families, add = corpus
    version, units = add(families[0], "partial", support_kinds=("factual", "voice"))
    partial = issue(
        user,
        families[0],
        version,
        units[0],
        value={"treatment": "partial", "selected_units": [str(units[0].id)]},
    )
    curation.review(user, partial.id, 0, "approve")
    plan = curation.build_plan(user, families[0].id, version.id)
    assert plan.eligible_units == [str(units[0].id)]
    assert plan.voice_units == []
    assert str(units[1].id) in plan.pending_units
    approval = issue(
        user,
        families[0],
        version,
        units[1],
        field="voice_approval",
        value={"approved": True},
        scope=f"unit:{units[1].id}",
    )
    with pytest.raises(ValueError, match="explicit human edit"):
        curation.review(user, approval.id, 0, "approve")
    curation.review(
        user,
        approval.id,
        0,
        "edit",
        value={"approved": True},
        rationale="Approved source-checked voice",
    )
    plan = curation.build_plan(user, families[0].id, version.id)
    assert plan.voice_units == [str(units[1].id)]
    assert plan.eligible_units == [str(units[0].id)]
    voice_exclusion = issue(
        user,
        families[0],
        version,
        units[1],
        scope=f"unit:{units[1].id}",
        value={"treatment": "excluded"},
    )
    curation.review(user, voice_exclusion.id, 0, "approve")
    plan = curation.build_plan(user, families[0].id, version.id)
    assert str(units[1].id) in plan.excluded_units
    assert str(units[1].id) not in plan.voice_units
    curation.record_fact(
        user,
        families[0].id,
        version.id,
        "sensitivity",
        "financial_sensitive",
        unit_id=units[0].id,
        rationale="Explicit policy label",
        evidence=[str(units[0].id)],
        origin="policy",
        resolver_revision="policy-v1",
    )
    plan = curation.build_plan(user, families[0].id, version.id)
    assert str(units[0].id) not in plan.eligible_units
    assert str(units[0].id) in plan.excluded_units
    curation.review(
        user,
        partial.id,
        1,
        "edit",
        value={
            "treatment": "summary",
            "source_units": [str(units[0].id)],
            "summary": "Derived synthetic summary",
            "voice_eligible": False,
        },
        rationale="Source-checked summary",
    )
    plan = curation.build_plan(user, families[0].id, version.id)
    assert not plan.derived_summaries  # policy prohibition still wins
    assert m.CurationPlan.objects.filter(version=version, state="invalidated").exists()


def test_derived_summary_links_source_and_cannot_be_voice_example(corpus):
    user, _, families, add = corpus
    version, units = add(families[0], "summary")
    recommendation = {
        "treatment": "summary",
        "source_units": [str(units[0].id)],
        "summary": "Synthetic derived overview",
        "voice_eligible": False,
    }
    decision = issue(user, families[0], version, units[0], value=recommendation)
    curation.review(user, decision.id, 0, "approve")
    plan = curation.build_plan(user, families[0].id, version.id)
    assert plan.eligible_units == []
    assert plan.derived_summaries[0]["source_units"] == [str(units[0].id)]
    assert plan.derived_summaries[0]["support_kind"] == "derived"
    assert plan.derived_summaries[0]["voice_eligible"] is False


def test_metadata_only_is_distinct_from_excluded_and_unresolved(corpus):
    user, _, families, add = corpus
    version, units = add(families[0], "metadata")
    decision = issue(
        user,
        families[0],
        version,
        units[0],
        scope=f"unit:{units[0].id}",
        value={"treatment": "metadata_only"},
    )
    curation.review(user, decision.id, 0, "approve")
    plan = curation.build_plan(user, families[0].id, version.id)
    assert plan.metadata_only_units == [str(units[0].id)]
    assert plan.pending_units == [str(units[1].id)]
    assert plan.excluded_units == []
    assert not plan.metadata_only
    second = issue(
        user,
        families[0],
        version,
        units[1],
        scope=f"unit:{units[1].id}",
        value={"treatment": "metadata_only"},
    )
    curation.review(user, second.id, 0, "approve")
    assert curation.build_plan(user, families[0].id, version.id).metadata_only


def test_critical_hidden_by_presentation_blocks_only_affected_unit(corpus):
    user, collection, families, add = corpus
    version, units = add(families[0], "hidden")
    for index in range(11):
        issue(
            user,
            families[0],
            version,
            units[0],
            scope=f"unit:{units[0].id}",
            kind=f"question-{index}",
            critical=True,
        )
    queue = curation.review_queue(collection.id)
    assert len(queue["visible"]) == 10
    assert queue["hidden_count"] == 1
    assert queue["critical_count"] == 11
    full = issue(user, families[0], version, units[0], kind="curation")
    curation.review(user, full.id, 0, "approve")
    plan = curation.build_plan(user, families[0].id, version.id)
    assert str(units[0].id) in plan.pending_units
    assert str(units[0].id) not in plan.eligible_units
    assert str(units[1].id) in plan.eligible_units
    assert curation.blocking_issues(families[0], version, units[0])
    assert not curation.blocking_issues(families[1], version, units[0])


def test_bounded_cross_document_reconciliation_has_semantic_entity_scope(corpus):
    user, _, families, add = corpus
    version_a, units_a = add(families[0], "target")
    version_b, units_b = add(families[0], "measurement")
    for version, unit, label in [
        (version_a, units_a[0], "target"),
        (version_b, units_b[0], "measurement"),
    ]:
        curation.record_fact(
            user,
            families[0].id,
            version.id,
            "claim_type",
            label,
            unit_id=unit.id,
            entity_key="cell-capacity",
            rationale="Synthetic labeled source",
            evidence=[str(unit.id)],
            origin="human",
            resolver_revision="test-v1",
        )
    issues = curation.reconcile_family(user, families[0].id)
    assert len(issues) == 1
    assert issues[0].scope == "entity:cell-capacity"
    assert issues[0].critical and issues[0].status == "unresolved"
    assert curation.reconcile_family(user, families[0].id)[0].id == issues[0].id
    assert not m.Decision.objects.filter(family=families[1]).exists()


def test_review_ui_authorizes_and_detects_concurrent_edit(corpus):
    user, collection, families, add = corpus
    version, units = add(families[0], "ui")
    decision = issue(user, families[0], version, units[0], critical=True)
    legacy = m.Decision.objects.create(
        family=families[0], scope=f"version:{version.id}", field="publication", kind="inclusion"
    )
    client = Client()
    client.force_login(user)
    queue = client.get(reverse("review-queue", args=[collection.id]))
    assert queue.status_code == 200 and b"Critical" in queue.content
    assert b"publication / inclusion" not in queue.content
    assert client.get(reverse("review-decision", args=[legacy.id])).status_code == 404
    detail = client.get(reverse("review-decision", args=[decision.id]))
    assert detail.status_code == 200 and b"Synthetic ui evidence" in detail.content
    target = reverse("review-decision", args=[decision.id])
    assert (
        client.post(
            target, {"action": "defer", "revision": 0, "rationale": "Need review"}
        ).status_code
        == 302
    )
    assert client.post(target, {"action": "approve", "revision": 0}).status_code == 409
    anonymous = Client()
    assert anonymous.get(target).status_code in {302, 401, 403}


@pytest.mark.django_db(transaction=True)
def test_browser_scoped_partial_review_and_undo(corpus, settings, live_server, monkeypatch):
    user, collection, families, add = corpus
    version, units = add(families[0], "browser")
    decision = issue(user, families[0], version, units[0], critical=True)
    monkeypatch.setattr(settings, "LOCAL_AUTH", True)
    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        dev._configure_browser_cache()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            assert (
                page.goto(live_server.url + reverse("review-decision", args=[decision.id])).status
                == 401
            )
            page.goto(live_server.url + "/login/")
            page.get_by_label("Local identity").fill("mvp05-owner")
            page.get_by_role("button", name="Sign in locally").click()
            page.goto(live_server.url + reverse("review-queue", args=[collection.id]))
            page.get_by_role("link", name="treatment / curation").click()
            assert "Synthetic browser evidence 0" in page.locator("body").inner_text()
            page.get_by_label("Treatment").select_option("partial")
            page.locator(f'input[name="selected_units"][value="{units[0].id}"]').check()
            page.get_by_label("Reason").first.fill("Use the first source-checked passage only")
            page.get_by_role("button", name="Save scoped edit").click()
            assert "resolved" in page.locator("body").inner_text()
            page.get_by_role("button", name="Undo last answer").click()
            assert "unresolved" in page.locator("body").inner_text()
        finally:
            browser.close()
    answer = m.DecisionEvent.objects.get(decision=decision, action="edit")
    assert answer.value == {"treatment": "partial", "selected_units": [str(units[0].id)]}
    assert m.Decision.objects.get(pk=decision.id).status == "unresolved"


class StubAdapter:
    live = False
    estimated_cost_usd = Decimal("0")

    def __init__(self, labels):
        self.labels = labels

    def available(self):
        return True

    def predict(self, case):
        label, confidence = self.labels[case.key]
        return evaluation.Prediction(label, confidence, 5, Decimal("0"), "synthetic-v1")


def test_comparison_reports_false_exclusion_contamination_abstention_and_split_guard(corpus):
    user, collection, _, _ = corpus
    cases = [
        evaluation.LabeledCase(
            "retain", "family-a", "treatment", "Synthetic evidence", "full", "version-a", "unit-a"
        ),
        evaluation.LabeledCase(
            "exclude",
            "family-b",
            "treatment",
            "Sensitive synthetic",
            "excluded",
            "version-b",
            "unit-b",
        ),
        evaluation.LabeledCase(
            "claim",
            "family-c",
            "claim_type",
            "A target, not measured",
            "target",
            "version-c",
            "unit-c",
        ),
    ]
    adapters = {
        "baseline": StubAdapter(
            {"retain": ("excluded", 0.9), "exclude": ("full", 0.8), "claim": ("target", 0.8)}
        ),
        "economical": StubAdapter(
            {"retain": ("full", None), "exclude": ("excluded", 0.7), "claim": ("model", 0.4)}
        ),
        "jev": StubAdapter(
            {"retain": ("full", 0.7), "exclude": ("excluded", 0.6), "claim": ("target", 0.8)}
        ),
    }
    report = evaluation.compare(user, collection.id, cases, adapters)
    assert report["baseline"]["metrics"]["false_exclusions"] == 1
    assert report["baseline"]["metrics"]["contamination"] == 1
    assert report["economical"]["metrics"]["abstained"] == 1
    assert report["jev"]["metrics"]["claim_type_correct"] == 1
    assert m.EvaluationRecord.objects.filter(run_id=report["run_id"]).count() == 3
    mixed = [
        cases[0],
        evaluation.LabeledCase(
            "another", "family-a", "claim_type", "Same group", "target", "v", "u", "frozen"
        ),
    ]
    with pytest.raises(ValueError, match="cannot cross"):
        evaluation.compare(user, collection.id, mixed, adapters, persist=False)


def test_private_case_excerpt_must_match_its_collection_unit(corpus):
    user, collection, families, add = corpus
    version, units = add(families[0], "private-source")
    adapters = {
        route: StubAdapter({"private": ("target", 0.8)})
        for route in ("baseline", "economical", "jev")
    }
    case = evaluation.LabeledCase(
        "private",
        "family-a",
        "claim_type",
        "Text from elsewhere",
        "target",
        str(version.id),
        str(units[0].id),
        "calibration",
    )
    with pytest.raises(ValueError, match="excerpt lacks collection source provenance"):
        evaluation.compare(user, collection.id, [case], adapters, persist=False)
    verified = evaluation.LabeledCase(
        "private",
        "family-a",
        "claim_type",
        units[0].text,
        "target",
        str(version.id),
        str(units[0].id),
        "calibration",
    )
    assert (
        evaluation.compare(user, collection.id, [verified], adapters, persist=False)["baseline"][
            "metrics"
        ]["correct"]
        == 1
    )


def test_provider_adapters_fail_closed_and_parse_typed_responses(corpus, settings, monkeypatch):
    _, _, _, _ = corpus
    case = evaluation.LabeledCase("c", "g", "claim_type", "Synthetic target", "target", "v", "u")

    class Bedrock:
        def converse(self, **kwargs):
            assert (
                kwargs["modelId"] == settings.APP["classification_routes"]["baseline"]["model_id"]
            )
            return {
                "output": {
                    "message": {
                        "content": [{"text": json.dumps({"label": "target", "confidence": 0.8})}]
                    }
                },
                "usage": {"inputTokens": 12, "outputTokens": 4},
            }

    result = evaluation.BedrockChoiceAdapter(
        "baseline", client=Bedrock(), estimated_cost_usd="0.001"
    ).predict(case)
    assert result.label == "target" and result.input_tokens == 12
    assert result.cost_usd == Decimal("0.001")
    app = copy.deepcopy(settings.APP)
    app["classification_routes"]["jev"]["enabled"] = True
    settings.APP = app
    monkeypatch.setenv("TYPESAFE_API_KEY", "synthetic-test-key")

    def transport(request, timeout):
        assert timeout == 20 and request.full_url == settings.APP["jev_api_url"]
        body = json.loads(request.data)
        assert body["questions"]["claim_type"]["type"] == "choice"
        return io.BytesIO(
            json.dumps(
                {
                    "model": "jev-test",
                    "answers": {"claim_type": {"choice": "target", "confidence": 0.75}},
                    "usage": {"input_tokens": 20, "output_tokens": 5},
                }
            ).encode()
        )

    jev = evaluation.JevChoiceAdapter(transport=transport, estimated_cost_usd="0.002")
    assert jev.predict(case).label == "target"
    private_case = evaluation.LabeledCase(
        "p", "g", "claim_type", "Private placeholder", "target", "v", "u", "calibration"
    )
    assert jev.predict(private_case).error == "terms_not_approved"
    missing = evaluation.BedrockChoiceAdapter("economical")
    assert missing.predict(case).error == "unavailable"
    route, _ = evaluation.route_for_task("claim_type")
    assert route == "baseline"

    class TimeoutBedrock:
        def converse(self, **kwargs):
            raise TimeoutError("fictional timeout")

    assert (
        evaluation.BedrockChoiceAdapter(
            "baseline", client=TimeoutBedrock(), estimated_cost_usd="0.001"
        )
        .predict(case)
        .error
        == "timeout"
    )

    class MalformedBedrock:
        def converse(self, **kwargs):
            return {"output": {"message": {"content": [{"text": "not json"}]}}}

    assert (
        evaluation.BedrockChoiceAdapter("baseline", client=MalformedBedrock()).predict(case).error
        == "malformed_response"
    )


def test_live_comparison_requires_opt_in_estimate_and_budget(corpus):
    user, collection, _, _ = corpus
    case = evaluation.LabeledCase(
        "one", "one-group", "claim_type", "Synthetic target", "target", "v", "u"
    )

    class LiveAdapter(StubAdapter):
        live = True
        estimated_cost_usd = Decimal("0.01")

    adapters = {
        route: LiveAdapter({"one": ("target", 0.8)}) for route in ("baseline", "economical", "jev")
    }
    disabled = evaluation.compare(
        user, collection.id, [case], adapters, max_spend_usd="0.03", persist=False
    )
    assert all(disabled[route]["predictions"][0]["error"] == "unavailable" for route in adapters)
    bounded = evaluation.compare(
        user,
        collection.id,
        [case],
        adapters,
        max_spend_usd="0.01",
        allow_live=True,
        persist=True,
    )
    assert bounded["baseline"]["predictions"][0]["label"] == "target"
    assert bounded["economical"]["predictions"][0]["error"] == "budget_stopped"
    assert bounded["jev"]["predictions"][0]["error"] == "budget_stopped"
    assert m.EvaluationCall.objects.filter(run_id=bounded["run_id"]).count() == 1
    assert m.BudgetAccount.objects.get(pk="setup").committed == Decimal("0.01")


def test_synthetic_comparison_command_prints_only_aggregate_metrics(corpus, settings):
    user, collection, _, _ = corpus
    output = io.StringIO()
    call_command(
        "evaluate_curation",
        collection=str(collection.id),
        user=user.username,
        cases=settings.ROOT / "sample_data/application_slice/curation_eval.json",
        mock=True,
        stdout=output,
    )
    report = json.loads(output.getvalue())
    assert report["metrics"]["baseline"]["correct"] == 4
    assert report["metrics"]["economical"]["false_exclusions"] == 1
    assert "proposed goal" not in output.getvalue()
