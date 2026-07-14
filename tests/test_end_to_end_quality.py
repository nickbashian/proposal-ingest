"""End-to-end quality benchmarks and proposal-aware RAG output checks (issue #9).

Unit-level question-arbitration nuances (duplicate-fact consolidation, budget
capping) are already covered by ``tests/test_question_arbiter.py`` and
``tests/test_proposal_synthesizer.py``; this file focuses on what those
narrower tests cannot exercise: the pipeline's behavior across a realistic,
multi-document proposal run end-to-end (scan through build-clean-set) and the
first-class proposal retrieval objects, enriched RAG manifest, and
provenance reports that come out the other side.

All assertions here run in ``--mock-bedrock`` mode and make no AWS calls, so
this suite stays deterministic and CI-safe.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from typer.testing import CliRunner

from proposal_ingest.analyzer import analyze_inventory
from proposal_ingest.clean_set_builder import build_clean_set
from proposal_ingest.cli import app
from proposal_ingest.folder_builder import build_all_folders
from proposal_ingest.metadata_store import MetadataStore
from proposal_ingest.proposal_synthesizer import (
    build_deterministic_proposal_metadata,
    synthesize_all_proposals,
)
from proposal_ingest.question_arbiter import arbitrate_all_proposals
from proposal_ingest.quality_benchmarks import evaluate_expected_outcomes, load_expected_outcomes
from proposal_ingest.retrieval_builder import build_document_manifest_rows
from proposal_ingest.scanner import scan_source_root
from proposal_ingest.schemas import (
    DocumentManifestEntry,
    DocumentMetadata,
    ManifestObjectType,
    ProposalRetrievalRecord,
)

from tests.test_proposal_synthesizer import _BASE_DOC, _make_doc

_runner = CliRunner()
_SAMPLE_ROOT = Path(__file__).resolve().parents[1] / "sample_data" / "quality_benchmark"
_EXPECTED_DIR = Path(__file__).resolve().parent / "fixtures" / "quality_benchmark" / "expected"


# ---------------------------------------------------------------------------
# Shared pipeline runner
# ---------------------------------------------------------------------------


class _PipelineResult:
    def __init__(self, run_dir: Path, store: MetadataStore, questions, clean_result) -> None:
        self.run_dir = run_dir
        self.store = store
        self.questions = questions
        self.clean_result = clean_result


def _run_pipeline(output_root: Path) -> _PipelineResult:
    """Run scan -> analyze(mock) -> synthesize -> arbitrate -> build-folders -> build-clean-set."""
    artifacts = scan_source_root(source_root=_SAMPLE_ROOT, output_root=output_root)
    analyze_inventory(
        artifacts.run_dir, artifacts.inventory_records, artifacts.run_id, use_mock=True
    )
    store = MetadataStore(artifacts.run_dir)
    proposal_results = synthesize_all_proposals(store, use_mock=True)
    arbitration_result = arbitrate_all_proposals(store, use_mock=True)
    build_all_folders(
        store,
        proposal_metadata_by_id={r.proposal_id: r.metadata for r in proposal_results},
        use_mock=True,
    )
    clean_result = build_clean_set(output_root, allow_critical_open=True, force=True)
    return _PipelineResult(artifacts.run_dir, store, arbitration_result.questions, clean_result)


def _proposal_by_branch(store: MetadataStore, branch: str):
    for proposal in store.load_proposal_metadata_by_id().values():
        if proposal.proposal_branch == branch:
            return proposal
    raise AssertionError(f"No synthesized proposal found for branch {branch!r}")


# ---------------------------------------------------------------------------
# Well-documented proposal: zero questions, differentiated document treatment
# ---------------------------------------------------------------------------


def test_well_documented_proposal_produces_zero_questions(tmp_path: Path) -> None:
    result = _run_pipeline(tmp_path)
    proposal = _proposal_by_branch(result.store, "Well Documented Battery SBIR")

    proposal_questions = [q for q in result.questions if q.proposal_id == proposal.proposal_id]
    assert proposal_questions == []


def test_well_documented_proposal_collapses_duplicate_file(tmp_path: Path) -> None:
    """A byte-identical duplicate file must not become a second retrieval object."""
    result = _run_pipeline(tmp_path)
    proposal = _proposal_by_branch(result.store, "Well Documented Battery SBIR")

    # 9 files on disk (including one duplicate) but only 8 distinct documents.
    assert proposal.document_count == 8
    assert len(proposal.document_lineage) == 8


def test_final_technical_volume_is_authoritative_and_draft_is_superseded(tmp_path: Path) -> None:
    result = _run_pipeline(tmp_path)
    proposal = _proposal_by_branch(result.store, "Well Documented Battery SBIR")

    lineage_by_file = {e.file_name_original: e for e in proposal.document_lineage}
    final_entry = lineage_by_file["Technical Volume FINAL.txt"]
    draft_entry = lineage_by_file["Technical Volume DRAFT.txt"]

    assert final_entry.is_authoritative is True
    assert draft_entry.is_authoritative is False
    assert draft_entry.superseded_by_document_id == final_entry.document_id

    treatment_by_id = {t.document_id: t for t in proposal.knowledge_base_treatment}
    assert (
        str(treatment_by_id[final_entry.document_id].recommended_rag_treatment) == "full_document"
    )
    assert str(treatment_by_id[final_entry.document_id].rag_priority) == "high"


def test_budget_excluded_from_future_rag(tmp_path: Path) -> None:
    result = _run_pipeline(tmp_path)
    proposal = _proposal_by_branch(result.store, "Well Documented Battery SBIR")

    lineage_by_file = {e.file_name_original: e for e in proposal.document_lineage}
    treatment_by_id = {t.document_id: t for t in proposal.knowledge_base_treatment}
    budget_id = lineage_by_file["Budget.txt"].document_id

    assert str(treatment_by_id[budget_id].recommended_rag_treatment) == "exclude"
    assert treatment_by_id[budget_id].policy_applied == "budgets_excluded_from_rag"


def test_evaluation_criteria_outranks_generic_opportunity_boilerplate(tmp_path: Path) -> None:
    """Evaluation criteria should get better treatment than a generic NOFO (issue #9, item 4)."""
    result = _run_pipeline(tmp_path)
    proposal = _proposal_by_branch(result.store, "Well Documented Battery SBIR")

    lineage_by_file = {e.file_name_original: e for e in proposal.document_lineage}
    treatment_by_id = {t.document_id: t for t in proposal.knowledge_base_treatment}

    nofo_treatment = treatment_by_id[lineage_by_file["NOFO Solicitation.txt"].document_id]
    eval_treatment = treatment_by_id[lineage_by_file["Evaluation Criteria.txt"].document_id]

    assert str(nofo_treatment.recommended_rag_treatment) == "metadata_only"
    assert str(eval_treatment.recommended_rag_treatment) != "metadata_only"


def test_reviewer_feedback_retained_as_high_value_context(tmp_path: Path) -> None:
    result = _run_pipeline(tmp_path)
    proposal = _proposal_by_branch(result.store, "Well Documented Battery SBIR")

    lineage_by_file = {e.file_name_original: e for e in proposal.document_lineage}
    treatment_by_id = {t.document_id: t for t in proposal.knowledge_base_treatment}
    feedback_id = lineage_by_file["Reviewer Feedback.txt"].document_id

    assert treatment_by_id[feedback_id].policy_applied == "high_value_roles"
    assert proposal.proposal_summary.reviewer_feedback != []


# ---------------------------------------------------------------------------
# Proposal-first-class retrieval object + enriched manifest + provenance
# ---------------------------------------------------------------------------


def test_proposal_retrieval_object_is_written_and_schema_valid(tmp_path: Path) -> None:
    result = _run_pipeline(tmp_path)
    proposal = _proposal_by_branch(result.store, "Well Documented Battery SBIR")
    branch_dir = result.store.mirror_branch_dir(proposal.year_folder, proposal.proposal_branch)

    retrieval_path = branch_dir / "retrieval" / "proposal_context.json"
    assert retrieval_path.exists()
    record = ProposalRetrievalRecord.model_validate_json(retrieval_path.read_text("utf-8"))
    assert record.proposal_id == proposal.proposal_id
    assert record.document_count == 8
    # First-class RAG object: no source document text is duplicated here.
    dumped = json.dumps(record.model_dump(mode="json"))
    assert "solid-state battery cell chemistry" not in dumped

    assert (branch_dir / "proposal_metadata.json").exists()
    assert (branch_dir / "provenance_report.json").exists()


def test_document_manifest_covers_rag_excluded_docs_that_are_still_copied(tmp_path: Path) -> None:
    result = _run_pipeline(tmp_path)
    proposal = _proposal_by_branch(result.store, "Well Documented Battery SBIR")
    branch_dir = result.store.mirror_branch_dir(proposal.year_folder, proposal.proposal_branch)

    manifest_path = branch_dir / "retrieval" / "document_manifest.jsonl"
    lines = [ln for ln in manifest_path.read_text("utf-8").splitlines() if ln.strip()]
    entries = [DocumentManifestEntry.model_validate_json(ln) for ln in lines]
    assert len(entries) == 8
    assert all(e.parent_proposal_record == proposal.proposal_id for e in entries)

    budget_entry = next(e for e in entries if e.file_name_original == "Budget.txt")
    assert str(budget_entry.recommended_rag_treatment) == "exclude"
    # Still copied to the clean set (budgets are RAG-excluded, not clean-set-excluded).
    assert budget_entry.local_clean_path is not None


def test_s3_manifest_has_one_proposal_record_row_and_relationship_fields(tmp_path: Path) -> None:
    result = _run_pipeline(tmp_path)
    manifest_lines = result.clean_result.manifest_path.read_text("utf-8").splitlines()
    rows = [json.loads(ln) for ln in manifest_lines if ln.strip()]

    well_documented_rows = [
        r
        for r in rows
        if r["proposal_id"]
        == _proposal_by_branch(result.store, "Well Documented Battery SBIR").proposal_id
    ]
    proposal_record_rows = [
        r for r in well_documented_rows if r["object_type"] == ManifestObjectType.proposal_record
    ]
    document_rows = [
        r for r in well_documented_rows if r["object_type"] == ManifestObjectType.document
    ]

    assert len(proposal_record_rows) == 1
    assert proposal_record_rows[0]["rag_priority"] == "high"
    assert len(document_rows) == 8
    assert all(r["parent_proposal_record"] == r["proposal_id"] for r in document_rows)
    assert all("document_role" in r for r in document_rows)


def test_run_level_quality_report_is_written(tmp_path: Path) -> None:
    result = _run_pipeline(tmp_path)
    report_path = result.clean_result.quality_report_path
    assert report_path is not None
    report = json.loads(report_path.read_text("utf-8"))

    assert report["proposal_count"] == 2
    assert "document_count_by_treatment" in report
    assert "questions_by_proposal" in report
    assert set(report["object_types_in_manifest"]) == {"proposal_record", "document"}


# ---------------------------------------------------------------------------
# Sensitivity restriction
# ---------------------------------------------------------------------------


def test_personal_info_document_restricted_from_clean_set(tmp_path: Path) -> None:
    result = _run_pipeline(tmp_path)
    proposal = _proposal_by_branch(result.store, "Sensitive Personal Info Proposal")
    branch_dir = result.store.mirror_branch_dir(proposal.year_folder, proposal.proposal_branch)

    documents_dir = branch_dir / "documents"
    copied_names = {p.name for p in documents_dir.glob("*")} if documents_dir.exists() else set()
    assert not any("Biosketch" in name for name in copied_names)

    excluded_rows = [
        json.loads(json.dumps(row))
        for row in result.clean_result.excluded_rows
        if row.get("proposal_id") == proposal.proposal_id
    ]
    assert any(
        "manual_review_required" in (row.get("exclusion_reason") or "") for row in excluded_rows
    )

    retrieval_path = branch_dir / "retrieval" / "proposal_context.json"
    record = ProposalRetrievalRecord.model_validate_json(retrieval_path.read_text("utf-8"))
    assert record.sensitivity_summary.manual_review_required_count >= 1
    assert record.sensitivity_summary.restricted_document_ids != []
    # Excluded from the clean-set copy, but still present in the full lineage/manifest.
    assert record.document_count == 2
    assert len(record.document_lineage) == 2

    manifest_path = branch_dir / "retrieval" / "document_manifest.jsonl"
    lines = [ln for ln in manifest_path.read_text("utf-8").splitlines() if ln.strip()]
    entries = [DocumentManifestEntry.model_validate_json(ln) for ln in lines]
    assert len(entries) == 2
    biosketch_entry = next(e for e in entries if "Biosketch" in (e.file_name_original or ""))
    assert biosketch_entry.local_clean_path is None
    assert str(biosketch_entry.recommended_rag_treatment) == "exclude"


# ---------------------------------------------------------------------------
# Question count does not scale with document count
# ---------------------------------------------------------------------------


def test_question_count_does_not_scale_with_document_count(tmp_path: Path) -> None:
    """A well-documented proposal with many consistent documents still yields zero questions."""
    store = MetadataStore(tmp_path / "logs" / "run_scale_test")
    for i in range(20):
        doc = copy.deepcopy(_BASE_DOC)
        doc["document_id"] = f"doc_scale_{i:03d}"
        doc["proposal_id"] = "prop_2025-scale-test__aaaaaaaa"
        doc["system"]["proposal_branch"] = "Scale Test Proposal"
        doc["system"]["file_name_original"] = f"Supporting Document {i:03d}.pdf"
        doc["document_identity"]["document_role"] = "final_report"
        doc["document_identity"]["version_status"] = "final"
        doc["uncertainties"] = []
        store.write_document_metadata(DocumentMetadata.model_validate(doc), append_jsonl=False)

    synthesize_all_proposals(store, use_mock=True, policies=[])
    result = arbitrate_all_proposals(store, use_mock=True)

    assert result.questions == []
    assert result.suppressed_count == 0


# ---------------------------------------------------------------------------
# evaluate-quality CLI command
# ---------------------------------------------------------------------------


def test_evaluate_quality_cli_passes_against_expected_fixtures(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    invoke_result = _runner.invoke(
        app,
        [
            "evaluate-quality",
            "--source-root",
            str(_SAMPLE_ROOT),
            "--output-root",
            str(output_root),
            "--mock-bedrock",
            "--expected",
            str(_EXPECTED_DIR),
        ],
    )

    assert invoke_result.exit_code == 0, invoke_result.output
    assert "PASS" in invoke_result.output
    assert "FAIL" not in invoke_result.output
    assert "2/2 proposal(s) passed" in invoke_result.output


def test_load_expected_outcomes_keys_by_proposal_branch() -> None:
    outcomes = load_expected_outcomes(_EXPECTED_DIR)
    assert "Well Documented Battery SBIR" in outcomes
    assert "Sensitive Personal Info Proposal" in outcomes


def test_evaluate_expected_outcomes_flags_question_count_regression(tmp_path: Path) -> None:
    result = _run_pipeline(tmp_path)
    proposal = _proposal_by_branch(result.store, "Well Documented Battery SBIR")

    mismatches = evaluate_expected_outcomes(
        proposal,
        question_count=3,
        expected={"max_question_count": 0},
    )
    assert mismatches != []
    assert "question_count" in mismatches[0]


def test_evaluate_quality_cli_fails_when_no_fixture_matches_a_proposal_branch(
    tmp_path: Path,
) -> None:
    """A fixture directory that exists but names the wrong branch must not look like a pass."""
    expected_dir = tmp_path / "expected"
    expected_dir.mkdir()
    (expected_dir / "nonexistent_branch.json").write_text(
        json.dumps({"proposal_branch": "Nonexistent Branch", "max_question_count": 0}),
        encoding="utf-8",
    )

    invoke_result = _runner.invoke(
        app,
        [
            "evaluate-quality",
            "--source-root",
            str(_SAMPLE_ROOT),
            "--output-root",
            str(tmp_path / "output"),
            "--mock-bedrock",
            "--expected",
            str(expected_dir),
        ],
    )

    assert invoke_result.exit_code != 0
    assert "none of the" in invoke_result.output


# ---------------------------------------------------------------------------
# Document manifest robustness against a stale proposal record
# ---------------------------------------------------------------------------


def test_document_manifest_includes_documents_missing_from_stale_lineage() -> None:
    """A document analyzed after the proposal's last synthesis must still get a row."""
    known_doc = _make_doc(document_id="doc_known_0001")
    proposal = build_deterministic_proposal_metadata([known_doc])
    assert len(proposal.document_lineage) == 1

    new_doc = _make_doc(document_id="doc_new_0002", file_name="New Document.pdf")
    rows = build_document_manifest_rows(proposal, [known_doc, new_doc])

    assert len(rows) == 2
    new_row = next(r for r in rows if r.document_id == "doc_new_0002")
    assert new_row.file_name_original == "New Document.pdf"
    assert new_row.document_role == new_doc.document_identity.document_role
