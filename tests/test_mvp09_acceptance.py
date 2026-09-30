from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from proposal_app.acceptance_harness import (
    ManifestError,
    assert_no_group_overlap,
    freeze_manifest,
    score_manifest,
    validate_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


def _complete_manifest():
    groups = [
        {"group_key": f"group-{family}", "split": "synthetic", "source_fingerprints": []}
        for family in ("F1", "F2", "F3")
    ]
    cases = []

    def add(metric, family, data, ordinal):
        cases.append(
            {
                "case_key": f"case-{metric}-{family}-{ordinal}",
                "family_key": family,
                "group_key": f"group-{family}",
                "split": "synthetic",
                "metric": metric,
                "data": data,
            }
        )

    for index, family in enumerate(("F1", "F2", "F3")):
        add("A01", family, {"disposition": "processed", "reason": "synthetic extraction"}, index)
        for passage in range(20):
            add(
                "A02",
                family,
                {
                    "valuable": True,
                    "retained": passage < 19,
                    "essential_conditions_preserved": passage < 19,
                    "critical": False,
                },
                passage,
            )
    for index in range(20):
        add(
            "A04",
            ("F1", "F2", "F3")[index % 3],
            {
                "answerable": True,
                "required_support_ids": [f"unit-{index}"],
                "top10_eligible_ids": [f"unit-{index}"] if index not in {2, 15} else [],
            },
            index,
        )
    for index in range(5):
        add(
            "A05",
            ("F1", "F2", "F3")[index % 3],
            {
                "case_kind": "gap" if index % 2 == 0 else "conflict",
                "observed": "gap" if index % 2 == 0 else "conflict",
                "unsupported_claims": 0,
            },
            index,
        )
        add(
            "A06",
            ("F1", "F2", "F3")[index % 3],
            {"citation_resolves": True, "semantic_support": True},
            index,
        )
        add(
            "A08",
            ("F1", "F2", "F3")[index % 3],
            {"usefulness_rating": 4 if index < 4 else 3, "ordinary_editing_only": True},
            index,
        )
    for index in range(20):
        add(
            "A07",
            ("F1", "F2", "F3")[index % 3],
            {"critical_error": index == 0, "flagged": index == 0},
            index,
        )
    for index, family in enumerate(("F1", "F2", "F3")):
        add(
            "A19",
            family,
            {
                "discovered_items": 1,
                "extracted_passages": 30,
                "supported_nonsensitive": 30,
                "automatically_tagged": 27,
                "automatically_resolved": 24,
                "substantive_questions": (3, 3, 4)[index],
                "human_decisions": 6,
                "review_seconds": 240,
                "unsupported_or_failed": 1,
            },
            index,
        )
    return {
        "schema_version": 1,
        "suite_id": "fictional-complete-gates",
        "kind": "synthetic",
        "source_snapshot": "fixture-only-v1",
        "policy_revision": "policy-fixture-v1",
        "schema_revision": "schema-fixture-v1",
        "prompt_revision": "prompt-fixture-v1",
        "sampling_method": "deterministic fixture generation",
        "inventory_counts": {"F1": 1, "F2": 1, "F3": 1},
        "groups": groups,
        "cases": cases,
    }


def test_frozen_revision_detects_changes_and_manifest_rejects_excerpts():
    frozen = freeze_manifest(_complete_manifest())
    validate_manifest(frozen)
    changed = copy.deepcopy(frozen)
    changed["cases"][0]["data"]["reason"] = "edited after freeze"
    with pytest.raises(ManifestError, match="revision"):
        validate_manifest(changed)
    candidate = _complete_manifest()
    candidate["cases"][0]["data"]["excerpt"] = "private source passage"
    with pytest.raises(ManifestError, match="source units"):
        freeze_manifest(candidate)


def test_related_content_cannot_cross_calibration_and_heldout_splits():
    calibration = _complete_manifest()
    calibration["kind"] = "calibration"
    calibration["frozen_by"] = "synthetic-owner-check"
    for group in calibration["groups"]:
        group["split"] = "calibration"
    for case in calibration["cases"]:
        case["split"] = "calibration"
    calibration = freeze_manifest(calibration)

    heldout = _complete_manifest()
    heldout["kind"] = "expansion_held_out"
    heldout["frozen_by"] = "synthetic-owner-check"
    heldout["groups"][0]["group_key"] = "heldout-related-content"
    heldout["groups"][0]["source_fingerprints"] = ["hmac-sha256:" + "a" * 64]
    for group in heldout["groups"]:
        group["split"] = "expansion_held_out"
    for case in heldout["cases"]:
        case["split"] = "expansion_held_out"
        if case["group_key"] == "group-F1":
            case["group_key"] = "heldout-related-content"
    heldout = freeze_manifest(heldout)

    calibration["groups"][0]["source_fingerprints"] = ["hmac-sha256:" + "a" * 64]
    calibration = freeze_manifest(calibration)
    with pytest.raises(ManifestError, match="overlap"):
        assert_no_group_overlap([calibration, heldout])


def test_duplicate_fingerprint_must_stay_in_one_group_even_within_a_split():
    manifest = _complete_manifest()
    fingerprint = "hmac-sha256:" + "b" * 64
    manifest["groups"][0]["source_fingerprints"] = [fingerprint]
    manifest["groups"][1]["source_fingerprints"] = [fingerprint]
    with pytest.raises(ManifestError, match="one leakage group"):
        freeze_manifest(manifest)


def test_answerable_retrieval_task_requires_support_to_avoid_vacuous_success():
    manifest = _complete_manifest()
    retrieval = next(case for case in manifest["cases"] if case["metric"] == "A04")
    retrieval["data"]["required_support_ids"] = []
    with pytest.raises(ManifestError, match="needs required support"):
        freeze_manifest(manifest)


def test_scoring_reports_per_family_denominators_and_hard_gate_results():
    report = score_manifest(freeze_manifest(_complete_manifest()))
    assert report["status"] == "pass"
    assert report["metrics"]["A02"]["totals"]["numerator"] == 57
    assert report["metrics"]["A02"]["totals"]["denominator"] == 60
    assert report["metrics"]["A02"]["families"]["F1"]["denominator"] == 20
    assert report["metrics"]["A04"]["totals"]["numerator"] == 18
    assert report["metrics"]["A19"]["totals"]["rate"] == 0.8
    assert report["metrics"]["A19"]["totals"]["substantive_questions"] == 10
    assert report["metrics"]["A07"]["totals"]["critical_unflagged"] == 0


def test_missing_inventory_disposition_fails_against_independent_denominator():
    manifest = _complete_manifest()
    manifest["cases"] = [
        case
        for case in manifest["cases"]
        if not (case["metric"] == "A01" and case["family_key"] == "F1")
    ]
    report = score_manifest(freeze_manifest(manifest))
    assert report["metrics"]["A01"]["families"]["F1"] == {
        "numerator": 0,
        "denominator": 1,
        "rate": 0.0,
        "critical_unflagged": 0,
        "critical_losses": 0,
        "case_count": 0,
        "substantive_questions": 0,
        "human_decisions": 0,
        "review_seconds": 0,
        "unsupported_or_failed": 0,
    }
    assert report["metrics"]["A01"]["status"] == "fail"


def test_small_fictional_fixture_is_pending_instead_of_claiming_acceptance():
    fixture_path = ROOT / "sample_data" / "acceptance_harness.synthetic.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    report = score_manifest(freeze_manifest(fixture))
    assert report["status"] == "pending"
    assert report["metrics"]["A02"]["status"] == "pending"
    assert report["metrics"]["A19"]["status"] == "pass"


def test_private_cli_writes_only_aggregate_report(tmp_path, monkeypatch, capsys):
    from scripts import evaluate_acceptance

    private_root = tmp_path / "private_evaluations"
    private_root.mkdir()
    monkeypatch.setattr(evaluate_acceptance, "ROOT", tmp_path)
    monkeypatch.setattr(evaluate_acceptance, "PRIVATE_ROOT", private_root.resolve())
    manifest = _complete_manifest()
    manifest["cases"][0]["case_key"] = "private-case-must-not-print"
    candidate = private_root / "candidate.json"
    candidate.write_text(json.dumps(manifest), encoding="utf-8")
    frozen_path = private_root / "frozen.json"
    assert (
        evaluate_acceptance.main(
            ["freeze", "--manifest", str(candidate), "--output", str(frozen_path)]
        )
        == 0
    )
    capsys.readouterr()
    report_path = private_root / "aggregate.json"
    assert (
        evaluate_acceptance.main(
            ["score", "--manifest", str(frozen_path), "--report", str(report_path)]
        )
        == 0
    )
    stdout = capsys.readouterr().out
    report_text = report_path.read_text(encoding="utf-8")
    assert "private-case-must-not-print" not in stdout
    assert "private-case-must-not-print" not in report_text
    assert "numerator" in report_text and "denominator" in report_text


def test_cli_refuses_manifest_or_report_outside_private_storage(tmp_path, monkeypatch):
    from scripts import evaluate_acceptance

    private_root = tmp_path / "private_evaluations"
    private_root.mkdir()
    outside = tmp_path / "public.json"
    outside.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(evaluate_acceptance, "ROOT", tmp_path)
    monkeypatch.setattr(evaluate_acceptance, "PRIVATE_ROOT", private_root.resolve())
    with pytest.raises(ManifestError, match="inside ignored"):
        evaluate_acceptance._private_path(outside)
