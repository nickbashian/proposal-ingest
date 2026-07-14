"""Return deterministic fake metadata for local testing without real AWS calls.

The mock analyzer infers document category and role from filename and extension only.
All confidence values are intentionally low/moderate and every record includes
``generated_by: mock_bedrock`` in processing_notes so callers can detect mock output.
"""

from __future__ import annotations

from proposal_ingest.schemas import (
    APP_SCHEMA_VERSION,
    Agency,
    ContentMetadata,
    DocumentCategory,
    DocumentConfidence,
    DocumentIdentity,
    DocumentMetadata,
    DocumentRole,
    InclusionMetadata,
    InventoryRecord,
    OpportunityTreatment,
    OriginType,
    ProcessingStatus,
    ProposalContext,
    RagPriority,
    RecommendedRagTreatment,
    SensitivityLabel,
    SensitivityMetadata,
    SystemMetadata,
    VersionStatus,
)

# ---------------------------------------------------------------------------
# Version-status / sensitivity keyword heuristics (filename only)
# ---------------------------------------------------------------------------

_VERSION_KEYWORDS: list[tuple[list[str], VersionStatus]] = [
    (["superseded", "obsolete", "old version"], VersionStatus.superseded),
    (["final"], VersionStatus.final),
    (["submitted"], VersionStatus.submitted_version),
    (["template", "blank"], VersionStatus.template),
    (["draft", "working", "wip", "old draft"], VersionStatus.draft),
]

_BUDGET_KEYWORDS = ["budget", "cost", "price", "pricing", "rate", "rates", "financial"]
_PERSONAL_INFO_KEYWORDS = ["ssn", "social security", "personal", "pii", "biosketch", "salary"]

_HIGH_VALUE_ROLES: frozenset[DocumentRole] = frozenset(
    {
        DocumentRole.technical_volume,
        DocumentRole.project_description,
        DocumentRole.statement_of_work,
        DocumentRole.award_notice,
        DocumentRole.review_feedback,
        DocumentRole.final_report,
        DocumentRole.milestone_report,
        DocumentRole.commercialization_plan,
    }
)

_LOW_VALUE_ROLES: frozenset[DocumentRole] = frozenset(
    {
        DocumentRole.rfp,
        DocumentRole.foa,
        DocumentRole.topic_description,
        DocumentRole.submission_instructions,
        DocumentRole.terms_and_conditions,
        DocumentRole.dfars_clauses,
    }
)

# ---------------------------------------------------------------------------
# Keyword-to-category/role heuristics (filename only, no content reading)
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS: list[tuple[list[str], DocumentCategory]] = [
    (
        ["budget", "cost", "price", "financial", "rates"],
        DocumentCategory.budget_financial,
    ),
    (
        ["technical", "tech", "volume", "approach", "narrative", "statement of work", "sow"],
        DocumentCategory.proposal_response,
    ),
    (
        [
            "rfp",
            "foa",
            "baa",
            "nofo",
            "solicitation",
            "opportunity",
            "announcement",
            "topic",
            "evaluation criteria",
        ],
        DocumentCategory.opportunity_document,
    ),
    (
        ["biosketch", "bio", "cv", "resume", "facilities", "equipment"],
        DocumentCategory.supporting_document,
    ),
    (
        ["letter", "support", "partner", "teaming", "mou"],
        DocumentCategory.partner_document,
    ),
    (
        ["data", "test", "measurement", "spec", "specification"],
        DocumentCategory.technical_data,
    ),
    (
        ["report", "milestone", "deliverable", "final"],
        DocumentCategory.report_or_deliverable,
    ),
    (
        ["presentation", "slides", "deck"],
        DocumentCategory.presentation,
    ),
    (
        ["plan", "internal", "roadmap", "strategy"],
        DocumentCategory.internal_planning,
    ),
]

_ROLE_KEYWORDS: list[tuple[list[str], DocumentRole]] = [
    (["technical volume", "tech vol", "technical narrative"], DocumentRole.technical_volume),
    (["project description", "project narrative"], DocumentRole.project_description),
    (
        ["commercialization", "market", "commercialization plan"],
        DocumentRole.commercialization_plan,
    ),
    (["statement of work", "sow"], DocumentRole.statement_of_work),
    (["budget justification", "budget narrative"], DocumentRole.budget_justification),
    (["budget", "cost"], DocumentRole.budget),
    (["quad chart", "quadchart"], DocumentRole.quad_chart),
    (["abstract", "executive summary"], DocumentRole.abstract),
    (["letter of support", "support letter", "letter"], DocumentRole.letter_of_support),
    (["facilities", "equipment"], DocumentRole.facilities_document),
    (["biosketch", "bio sketch", "cv", "resume"], DocumentRole.biosketch),
    (["data management", "dmp"], DocumentRole.data_management_plan),
    (["current and pending", "other support"], DocumentRole.current_pending_support),
    (["evaluation criteria", "evaluation guidance"], DocumentRole.evaluation_criteria),
    (["rfp", "baa", "solicitation"], DocumentRole.rfp),
    (["foa", "funding opportunity", "nofo"], DocumentRole.foa),
    (["topic description", "topic"], DocumentRole.topic_description),
    (["submission instructions", "instructions"], DocumentRole.submission_instructions),
    (["terms and conditions", "terms"], DocumentRole.terms_and_conditions),
    (["award notice", "award"], DocumentRole.award_notice),
    (["review", "feedback", "reviewer comments"], DocumentRole.review_feedback),
    (["milestone report", "progress report", "milestone"], DocumentRole.milestone_report),
    (["final report"], DocumentRole.final_report),
]

_EXTENSION_CATEGORY: dict[str, DocumentCategory] = {
    ".pdf": DocumentCategory.proposal_response,
    ".docx": DocumentCategory.proposal_response,
    ".doc": DocumentCategory.proposal_response,
    ".xlsx": DocumentCategory.budget_financial,
    ".xls": DocumentCategory.budget_financial,
    ".csv": DocumentCategory.technical_data,
    ".txt": DocumentCategory.supporting_document,
    ".md": DocumentCategory.internal_planning,
}


def _infer_category(stem: str, extension: str) -> tuple[DocumentCategory, float]:
    """Return the best-guess category and a low/moderate confidence score."""
    lower = stem.lower()
    for keywords, category in _CATEGORY_KEYWORDS:
        if any(kw in lower for kw in keywords):
            return category, 0.45
    # Fall back to extension-based guess
    cat = _EXTENSION_CATEGORY.get(extension.lower(), DocumentCategory.unknown)
    confidence = 0.30 if cat is DocumentCategory.unknown else 0.35
    return cat, confidence


def _infer_role(stem: str) -> tuple[DocumentRole, float]:
    """Return the best-guess role and a low/moderate confidence score."""
    lower = stem.lower()
    for keywords, role in _ROLE_KEYWORDS:
        if any(kw in lower for kw in keywords):
            return role, 0.40
    return DocumentRole.unknown, 0.25


def _infer_origin(category: DocumentCategory) -> OriginType:
    if category == DocumentCategory.opportunity_document:
        return OriginType.source_opportunity
    if category in {
        DocumentCategory.proposal_response,
        DocumentCategory.supporting_document,
    }:
        return OriginType.generated_response
    return OriginType.unknown


def _infer_program(branch_name: str) -> str:
    lower = branch_name.lower()
    if "sbir" in lower:
        return "SBIR"
    if "sttr" in lower:
        return "STTR"
    if "foa" in lower:
        return "FOA"
    if "baa" in lower:
        return "BAA"
    return "unknown"


def _infer_agency(branch_name: str) -> Agency:
    lower = branch_name.lower()
    if any(k in lower for k in ["doe", "energy", "arpa-e", "arpa_e"]):
        return Agency.doe
    if any(k in lower for k in ["dod", "defense", "army", "navy", "air force", "darpa"]):
        return Agency.dod
    if "nsf" in lower:
        return Agency.nsf
    if "nasa" in lower:
        return Agency.nasa
    return Agency.unknown


def _infer_version_status(stem: str) -> tuple[VersionStatus, str]:
    """Return the best-guess version status and supporting evidence text.

    Deliberately keyword-only (no content reading), matching the rest of
    this module's mock heuristics: this is what lets file-based benchmark
    fixtures exercise real draft/final/superseded standing policies through
    ``--mock-bedrock`` without any AWS calls.
    """
    lower = stem.lower()
    for keywords, version in _VERSION_KEYWORDS:
        for keyword in keywords:
            if keyword in lower:
                return version, f"Filename contains '{keyword}' (mock mode)."
    return VersionStatus.unknown, "No version keyword found in filename (mock mode)."


def _infer_sensitivity(stem: str, category: DocumentCategory) -> SensitivityMetadata:
    lower = stem.lower()
    labels: list[SensitivityLabel] = []
    contains_budget = category == DocumentCategory.budget_financial or any(
        kw in lower for kw in _BUDGET_KEYWORDS
    )
    contains_personal = any(kw in lower for kw in _PERSONAL_INFO_KEYWORDS)

    if contains_budget:
        labels.append(SensitivityLabel.financial_sensitive)
    if contains_personal:
        labels.append(SensitivityLabel.personal_info)

    reasons = []
    if contains_personal:
        reasons.append("Filename indicates personal information (mock mode).")

    return SensitivityMetadata(
        sensitivity_labels=labels,
        contains_budget_or_rates=contains_budget,
        contains_personal_info=contains_personal,
        manual_review_required=contains_personal,
        manual_review_reasons=reasons,
    )


def _infer_opportunity_treatment(stem: str, category: DocumentCategory) -> OpportunityTreatment:
    if category != DocumentCategory.opportunity_document:
        return OpportunityTreatment()

    if "evaluation" in stem.lower():
        return OpportunityTreatment(
            opportunity_context_useful=True,
            boilerplate_heavy=False,
            useful_context_summary=(
                "Filename indicates evaluation-criteria content, treated as useful "
                "opportunity context rather than generic boilerplate (mock mode)."
            ),
            recommended_rag_treatment=RecommendedRagTreatment.summary_only,
        )

    return OpportunityTreatment(
        opportunity_context_useful=False,
        boilerplate_heavy=True,
        boilerplate_summary="Generic opportunity/solicitation document (mock mode).",
        recommended_rag_treatment=RecommendedRagTreatment.metadata_only,
    )


def _infer_rag_priority(
    role: DocumentRole,
    version: VersionStatus,
    sensitivity: SensitivityMetadata,
) -> RagPriority:
    if sensitivity.contains_budget_or_rates or sensitivity.contains_personal_info:
        return RagPriority.exclude
    if role in _LOW_VALUE_ROLES:
        return RagPriority.low
    if version == VersionStatus.superseded:
        return RagPriority.low
    if version in (VersionStatus.draft, VersionStatus.working_version):
        return RagPriority.low
    if role in _HIGH_VALUE_ROLES and version in (
        VersionStatus.final,
        VersionStatus.submitted_version,
    ):
        return RagPriority.high
    if role in _HIGH_VALUE_ROLES:
        return RagPriority.medium
    return RagPriority.medium


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_document_mock(record: InventoryRecord, run_id: str) -> DocumentMetadata:
    """Return a deterministic, schema-valid DocumentMetadata without calling AWS.

    Infers category and role from the filename stem and extension.  All
    confidence scores are set low/moderate.  Every record includes
    ``generated_by: mock_bedrock`` in processing_notes.
    """
    stem = record.file_name_original.rsplit(".", 1)[0]
    category, cat_conf = _infer_category(stem, record.extension)
    role, role_conf = _infer_role(stem)
    origin = _infer_origin(category)
    program_str = _infer_program(record.proposal_branch)
    agency = _infer_agency(record.proposal_branch)
    version, version_evidence = _infer_version_status(stem)
    sensitivity = _infer_sensitivity(stem, category)
    opportunity_treatment = _infer_opportunity_treatment(stem, category)
    rag_priority = _infer_rag_priority(role, version, sensitivity)

    low_confidence = 0.30
    moderate_confidence = 0.45

    include_in_future_rag = record.eligible_for_processing and rag_priority != RagPriority.exclude

    return DocumentMetadata(
        schema_version=APP_SCHEMA_VERSION,
        document_id=record.document_id,
        proposal_id=record.proposal_id,
        run_id=run_id,
        system=SystemMetadata(
            source_path=record.source_path,
            relative_path=record.relative_path,
            year_folder=record.year_folder,
            proposal_branch=record.proposal_branch,
            file_name_original=record.file_name_original,
            file_name_safe=record.file_name_safe,
            extension=record.extension,
            size_bytes=record.size_bytes,
            modified_time=record.modified_time,
            sha256=record.sha256,
            processing_strategy=record.processing_strategy,
            processing_status=ProcessingStatus.processed_pass1,
        ),
        document_identity=DocumentIdentity(
            canonical_document_title=stem,
            document_category=category,
            document_role=role,
            origin_type=origin,
            version_status=version,
            draft_or_final_evidence=version_evidence,
            language="unknown",
            document_date=None,
        ),
        proposal_context=ProposalContext(
            canonical_proposal_name=record.proposal_branch,
            proposal_short_name=None,
            agency=agency,
            program=program_str,  # type: ignore[arg-type]
            status="unknown",  # type: ignore[arg-type]
            award_status="unknown",
        ),
        content=ContentMetadata(
            summary_short=f"Mock summary for {record.file_name_original}.",
            summary_detailed="",
            primary_topics=[],
            technical_keywords=[],
            technologies=[],
            applications=[],
        ),
        opportunity_treatment=opportunity_treatment,
        inclusion=InclusionMetadata(
            include_in_clean_set=record.eligible_for_processing,
            include_in_future_rag=include_in_future_rag,
            rag_priority=rag_priority,
            include_reason=(
                "Eligible document (mock mode)." if record.eligible_for_processing else None
            ),
            exclude_reason=(
                None if record.eligible_for_processing else "Not eligible for processing."
            ),
        ),
        sensitivity=sensitivity,
        confidence=DocumentConfidence(
            document_category=cat_conf,
            document_role=role_conf,
            origin_type=low_confidence,
            version_status=low_confidence,
            canonical_proposal_name=moderate_confidence,
            agency=low_confidence,
            program=low_confidence,
            status=low_confidence,
            award_status=low_confidence,
            include_in_clean_set=moderate_confidence,
            include_in_future_rag=moderate_confidence,
            rag_priority=moderate_confidence,
        ),
        processing_notes=["generated_by: mock_bedrock"],
    )
