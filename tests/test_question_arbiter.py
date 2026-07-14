"""Tests for proposal-level question arbitration (issue #8)."""

from __future__ import annotations

from pathlib import Path

from proposal_ingest.config import RuntimeConfig
from proposal_ingest.human_overrides import append_human_override, human_overrides_path
from proposal_ingest.metadata_store import MetadataStore
from proposal_ingest.proposal_synthesizer import synthesize_all_proposals
from proposal_ingest.question_arbiter import arbitrate_all_proposals, stable_proposal_question_id
from proposal_ingest.schemas import HumanOverrideRecord, QuestionPriority

from tests.test_proposal_synthesizer import _make_doc, _proposal_uncertainty

_POLICIES: list[dict[str, str]] = []


def _run_dir(tmp_path: Path, name: str = "run_001") -> Path:
    """Build a run_dir shaped like output_root/logs/run_xxx, matching the real pipeline."""
    return tmp_path / "logs" / name


# ---------------------------------------------------------------------------
# Normal (zero-question) result
# ---------------------------------------------------------------------------


def test_no_unresolved_decisions_yields_zero_questions(tmp_path: Path) -> None:
    store = MetadataStore(_run_dir(tmp_path))
    doc = _make_doc(document_id="doc_001", proposal_id="prop_aaa")
    store.write_document_metadata(doc, append_jsonl=False)
    synthesize_all_proposals(store, use_mock=True, policies=_POLICIES)

    result = arbitrate_all_proposals(store, use_mock=True, config=RuntimeConfig())

    assert result.questions == []
    assert result.suppressed_count == 0
    assert result.resolved_by_override_count == 0
    assert result.proposal_count == 1


# ---------------------------------------------------------------------------
# Duplicate suppression / consolidation
# ---------------------------------------------------------------------------


def test_duplicate_document_uncertainties_yield_one_canonical_question(tmp_path: Path) -> None:
    """Many documents flagging the same field must produce exactly one question."""
    store = MetadataStore(_run_dir(tmp_path))
    docs = [
        _make_doc(
            document_id="doc_001", proposal_id="prop_aaa", uncertainties=[_proposal_uncertainty()]
        ),
        _make_doc(
            document_id="doc_002", proposal_id="prop_aaa", uncertainties=[_proposal_uncertainty()]
        ),
        _make_doc(
            document_id="doc_003", proposal_id="prop_aaa", uncertainties=[_proposal_uncertainty()]
        ),
    ]
    for doc in docs:
        store.write_document_metadata(doc, append_jsonl=False)
    synthesize_all_proposals(store, use_mock=True, policies=_POLICIES)

    result = arbitrate_all_proposals(store, use_mock=True, config=RuntimeConfig())

    matching = [q for q in result.questions if q.field == "proposal_context.award_status"]
    assert len(matching) == 1
    affected = set((matching[0].affected_document_ids or "").split("|"))
    assert affected == {"doc_001", "doc_002", "doc_003"}


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


def test_proposal_budget_caps_questions_per_proposal(tmp_path: Path) -> None:
    store = MetadataStore(_run_dir(tmp_path))
    fields = ["award_status", "status", "submission_date", "sensitivity_labels"]
    docs = [
        _make_doc(
            document_id=f"doc_{i:03}",
            proposal_id="prop_aaa",
            uncertainties=[
                _proposal_uncertainty(field=f"proposal_context.{field}")
                | {"downstream_impact": "critical"}
            ],
        )
        for i, field in enumerate(fields)
    ]
    for doc in docs:
        store.write_document_metadata(doc, append_jsonl=False)
    synthesize_all_proposals(store, use_mock=True, policies=_POLICIES)

    config = RuntimeConfig()
    config.review.max_questions_per_proposal = 2
    config.review.max_questions_per_run = 20
    result = arbitrate_all_proposals(store, use_mock=True, config=config)

    assert len(result.questions) == 2
    assert result.suppressed_count == len(fields) - 2


def test_run_wide_budget_caps_total_across_proposals(tmp_path: Path) -> None:
    store = MetadataStore(_run_dir(tmp_path))
    for proposal_id in ("prop_aaa", "prop_bbb"):
        for i, field in enumerate(["award_status", "status"]):
            doc = _make_doc(
                document_id=f"doc_{proposal_id}_{i}",
                proposal_id=proposal_id,
                uncertainties=[
                    _proposal_uncertainty(field=f"proposal_context.{field}")
                    | {"downstream_impact": "critical"}
                ],
            )
            store.write_document_metadata(doc, append_jsonl=False)
    synthesize_all_proposals(store, use_mock=True, policies=_POLICIES)

    config = RuntimeConfig()
    config.review.max_questions_per_proposal = 5
    config.review.max_questions_per_run = 2
    result = arbitrate_all_proposals(store, use_mock=True, config=config)

    assert len(result.questions) == 2
    assert result.suppressed_count == 2


def test_low_priority_suppressed_by_default(tmp_path: Path) -> None:
    store = MetadataStore(_run_dir(tmp_path))
    doc = _make_doc(
        document_id="doc_001",
        proposal_id="prop_aaa",
        uncertainties=[_proposal_uncertainty() | {"downstream_impact": "low"}],
    )
    store.write_document_metadata(doc, append_jsonl=False)
    synthesize_all_proposals(store, use_mock=True, policies=_POLICIES)

    config = RuntimeConfig()
    config.review.include_low_priority = False
    result = arbitrate_all_proposals(store, use_mock=True, config=config)
    assert result.questions == []
    assert result.suppressed_count == 1

    config.review.include_low_priority = True
    result = arbitrate_all_proposals(store, use_mock=True, config=config)
    assert len(result.questions) == 1
    assert result.questions[0].priority == QuestionPriority.low


# ---------------------------------------------------------------------------
# Stable IDs
# ---------------------------------------------------------------------------


def test_stable_question_id_independent_of_wording_and_documents() -> None:
    first = stable_proposal_question_id("prop_aaa", "proposal", "proposal_fact", "award_status")
    second = stable_proposal_question_id("prop_aaa", "proposal", "proposal_fact", "award_status")
    assert first == second

    different_proposal = stable_proposal_question_id(
        "prop_bbb", "proposal", "proposal_fact", "award_status"
    )
    assert different_proposal != first


def test_stable_question_id_matches_generated_question(tmp_path: Path) -> None:
    store = MetadataStore(_run_dir(tmp_path))
    doc = _make_doc(
        document_id="doc_001", proposal_id="prop_aaa", uncertainties=[_proposal_uncertainty()]
    )
    store.write_document_metadata(doc, append_jsonl=False)
    synthesize_all_proposals(store, use_mock=True, policies=_POLICIES)

    result = arbitrate_all_proposals(store, use_mock=True, config=RuntimeConfig())
    assert len(result.questions) == 1
    expected_id = stable_proposal_question_id(
        "prop_aaa", "proposal", "proposal_fact", "award_status"
    )
    assert result.questions[0].question_id == expected_id


# ---------------------------------------------------------------------------
# Prior answers and reopening on conflicting evidence
# ---------------------------------------------------------------------------


def test_prior_override_suppresses_matching_candidate(tmp_path: Path) -> None:
    store = MetadataStore(_run_dir(tmp_path))
    doc = _make_doc(
        document_id="doc_001", proposal_id="prop_aaa", uncertainties=[_proposal_uncertainty()]
    )
    store.write_document_metadata(doc, append_jsonl=False)
    synthesize_all_proposals(store, use_mock=True, policies=_POLICIES)

    question_id = stable_proposal_question_id(
        "prop_aaa", "proposal", "proposal_fact", "award_status"
    )
    append_human_override(
        tmp_path,
        HumanOverrideRecord(
            question_id=question_id,
            scope="proposal",
            proposal_id="prop_aaa",
            field="proposal_context.award_status",
            decision_type="proposal_fact",
            affected_document_ids=["doc_001"],
            previous_value=None,
            applied_value="awarded",
            timestamp="2026-07-14T00:00:00+00:00",
            source="human_review",
        ),
    )

    result = arbitrate_all_proposals(store, use_mock=True, config=RuntimeConfig())

    assert result.questions == []
    assert result.resolved_by_override_count == 1
    assert human_overrides_path(tmp_path).exists()


def test_conflicting_new_evidence_reopens_question(tmp_path: Path) -> None:
    store = MetadataStore(_run_dir(tmp_path))
    doc = _make_doc(
        document_id="doc_001", proposal_id="prop_aaa", uncertainties=[_proposal_uncertainty()]
    )
    store.write_document_metadata(doc, append_jsonl=False)
    synthesize_all_proposals(store, use_mock=True, policies=_POLICIES)

    question_id = stable_proposal_question_id(
        "prop_aaa", "proposal", "proposal_fact", "award_status"
    )
    # The previously applied answer ("rejected") conflicts with the fresh
    # candidate's current_guess ("awarded" from _proposal_uncertainty()).
    append_human_override(
        tmp_path,
        HumanOverrideRecord(
            question_id=question_id,
            scope="proposal",
            proposal_id="prop_aaa",
            field="proposal_context.award_status",
            decision_type="proposal_fact",
            affected_document_ids=["doc_001"],
            previous_value=None,
            applied_value="rejected",
            timestamp="2026-07-14T00:00:00+00:00",
            source="human_review",
        ),
    )

    result = arbitrate_all_proposals(store, use_mock=True, config=RuntimeConfig())

    assert len(result.questions) == 1
    assert result.resolved_by_override_count == 0
    assert "Reopened" in (result.questions[0].why_human_input_is_needed or "")
