"""Synthesize proposal-branch folder metadata and Markdown summaries."""

from __future__ import annotations

import json
import textwrap
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from proposal_ingest.logging_utils import get_logger
from proposal_ingest.metadata_store import MetadataStore
from proposal_ingest.schemas import (
    Agency,
    DocumentMetadata,
    DocumentRole,
    FolderKeyDocument,
    FolderMetadata,
    OriginType,
    Program,
    ProposalStatus,
    RagPriority,
    SensitivityLabel,
    TrackerMatchStatus,
)
from proposal_ingest.tracker import TrackerRow, _normalize_status, match_tracker_row

logger = get_logger("folder_builder")

# ---------------------------------------------------------------------------
# Key document priority
# ---------------------------------------------------------------------------

_KEY_DOCUMENT_ROLES: list[DocumentRole] = [
    DocumentRole.technical_volume,
    DocumentRole.project_description,
    DocumentRole.statement_of_work,
    DocumentRole.commercialization_plan,
    DocumentRole.budget,
    DocumentRole.budget_justification,
    DocumentRole.abstract,
    DocumentRole.rfp,
    DocumentRole.foa,
    DocumentRole.award_notice,
    DocumentRole.quad_chart,
    DocumentRole.final_report,
    DocumentRole.milestone_report,
]

_MAX_KEY_DOCUMENTS = 10
_MAX_TECHNICAL_FOCUS = 20
_MAX_COMMERCIAL_FOCUS = 10
_SUMMARY_DETAIL_MAX_DOCS = 5
_SUMMARY_EXCERPT_CHARS = 500


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class FolderBuildResult:
    """Outcome of synthesizing one proposal folder."""

    proposal_id: str
    metadata: FolderMetadata
    json_path: Path
    summary_md_path: Path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_folder_metadata(
    documents: list[DocumentMetadata],
    *,
    tracker_rows: list[TrackerRow] | None = None,
    use_mock: bool = True,
    config: Any = None,
) -> FolderMetadata:
    """Synthesize a FolderMetadata record from a list of per-document metadata.

    All documents must share the same proposal_id.  The tracker_rows list is
    optional; when provided, match_tracker_row is called to override
    high-authority fields.  When use_mock=True, summaries are template-based;
    otherwise a single Bedrock call generates narrative text.
    """
    if not documents:
        raise ValueError("documents must be non-empty")

    first = documents[0]
    proposal_id = first.proposal_id
    year_folder = first.system.year_folder
    proposal_branch = first.system.proposal_branch

    # --- aggregated context fields ---
    canonical_proposal_name = _consensus_str(
        [d.proposal_context.canonical_proposal_name for d in documents],
        fallback=proposal_branch,
        ignore={"unknown", ""},
    )
    agency = _consensus_enum(
        [str(d.proposal_context.agency) for d in documents],
        default=Agency.unknown.value,
        ignore={Agency.unknown.value},
    )
    program = _consensus_enum(
        [str(d.proposal_context.program) for d in documents],
        default=Program.unknown.value,
        ignore={Program.unknown.value},
    )
    status_str = _consensus_enum(
        [str(d.proposal_context.status) for d in documents],
        default=ProposalStatus.unknown.value,
        ignore={ProposalStatus.unknown.value},
    )
    award_status = _consensus_str(
        [d.proposal_context.award_status for d in documents],
        fallback="unknown",
        ignore={"unknown", ""},
    )
    submission_date = _first_non_none([d.proposal_context.submission_date for d in documents])
    phase = _first_non_none([d.proposal_context.phase for d in documents])
    topic_number = _first_non_none([d.proposal_context.topic_number for d in documents])
    topic_title = _first_non_none([d.proposal_context.topic_title for d in documents])
    solicitation_number = _first_non_none(
        [d.proposal_context.solicitation_number for d in documents]
    )
    lead_organization = _first_non_none([d.proposal_context.lead_organization for d in documents])
    prime_or_sub = _consensus_str(
        [d.proposal_context.prime_or_sub for d in documents],
        fallback="unknown",
        ignore={"unknown", ""},
    )
    partners = _union_lists([d.proposal_context.partners for d in documents])
    technical_focus = _union_lists(
        [d.content.primary_topics + d.content.technologies for d in documents]
    )[:_MAX_TECHNICAL_FOCUS]
    commercial_focus = _union_lists([d.content.applications for d in documents])[
        :_MAX_COMMERCIAL_FOCUS
    ]

    # --- document counts ---
    included_docs = [d for d in documents if d.inclusion.include_in_clean_set]
    manual_review_docs = [d for d in documents if d.sensitivity.manual_review_required]
    excluded_docs = [
        d
        for d in documents
        if not d.inclusion.include_in_clean_set and not d.sensitivity.manual_review_required
    ]

    open_critical = sum(
        1
        for d in documents
        for q in d.questions_for_user
        if str(q.priority) == "critical" and str(q.status) == "open"
    )

    key_documents = _identify_key_documents(documents)

    # --- tracker ---
    tracker_match_status: TrackerMatchStatus = TrackerMatchStatus.not_attempted
    tracker_disagreements: list[dict[str, Any]] = []
    selection_notification_date: str | None = None
    award_date: str | None = None

    if tracker_rows:
        (
            tracker_match_status,
            canonical_proposal_name,
            submission_date,
            selection_notification_date,
            award_date,
            status_str,
            award_status,
            tracker_disagreements,
        ) = _apply_tracker_to_folder(
            proposal_branch=proposal_branch,
            tracker_rows=tracker_rows,
            canonical_proposal_name=canonical_proposal_name,
            submission_date=submission_date,
            status_str=status_str,
            award_status=award_status,
        )

    # --- readiness ---
    has_export_control = any(
        SensitivityLabel.export_control_review in d.sensitivity.sensitivity_labels
        for d in documents
        if d.sensitivity.manual_review_required
    )
    ready_for_clean_set = len(included_docs) > 0 and open_critical == 0
    ready_for_future_s3 = ready_for_clean_set and not has_export_control

    # --- summaries ---
    (
        folder_summary_short,
        folder_summary_detailed,
        opportunity_context_summary,
        generated_response_summary,
    ) = _build_summaries(
        documents,
        canonical_proposal_name=canonical_proposal_name,
        agency=agency,
        program=program,
        status_str=status_str,
        included_docs=included_docs,
        use_mock=use_mock,
        config=config,
    )

    return FolderMetadata(
        proposal_id=proposal_id,
        year_folder=year_folder,
        proposal_branch=proposal_branch,
        canonical_proposal_name=canonical_proposal_name,
        agency=agency,  # type: ignore[arg-type]
        program=program,  # type: ignore[arg-type]
        phase=phase,
        topic_number=topic_number,
        topic_title=topic_title,
        solicitation_number=solicitation_number,
        submission_date=submission_date,
        selection_notification_date=selection_notification_date,
        award_date=award_date,
        status=status_str,  # type: ignore[arg-type]
        award_status=award_status,
        lead_organization=lead_organization,
        prime_or_sub=prime_or_sub,
        partners=partners,
        technical_focus=technical_focus,
        commercial_focus=commercial_focus,
        folder_summary_short=folder_summary_short,
        folder_summary_detailed=folder_summary_detailed,
        opportunity_context_summary=opportunity_context_summary,
        generated_response_summary=generated_response_summary,
        key_documents=key_documents,
        included_document_count=len(included_docs),
        excluded_document_count=len(excluded_docs),
        manual_review_count=len(manual_review_docs),
        open_critical_questions=open_critical,
        ready_for_clean_set=ready_for_clean_set,
        ready_for_future_s3=ready_for_future_s3,
        tracker_match_status=tracker_match_status,
        tracker_disagreements=tracker_disagreements,
    )


def build_all_folders(
    store: MetadataStore,
    *,
    tracker_rows: list[TrackerRow] | None = None,
    use_mock: bool = True,
    config: Any = None,
) -> list[FolderBuildResult]:
    """Load all document metadata from store, group by proposal_id, synthesize."""
    docs_by_proposal: dict[str, list[DocumentMetadata]] = {}
    for doc in store.load_document_metadata_by_id().values():
        docs_by_proposal.setdefault(doc.proposal_id, []).append(doc)

    results: list[FolderBuildResult] = []
    for proposal_id in sorted(docs_by_proposal):
        docs = docs_by_proposal[proposal_id]
        logger.info("Building folder metadata for %s (%d docs)", proposal_id, len(docs))
        try:
            metadata = build_folder_metadata(
                docs,
                tracker_rows=tracker_rows,
                use_mock=use_mock,
                config=config,
            )
        except Exception:
            logger.exception("Failed to build folder metadata for %s", proposal_id)
            continue

        json_path = store.write_folder_metadata(metadata)
        summary_text = render_folder_summary_markdown(metadata)
        summary_md_path = json_path.with_suffix(".md")
        summary_md_path.write_text(summary_text, encoding="utf-8")

        results.append(
            FolderBuildResult(
                proposal_id=proposal_id,
                metadata=metadata,
                json_path=json_path,
                summary_md_path=summary_md_path,
            )
        )
    return results


def render_folder_summary_markdown(metadata: FolderMetadata) -> str:
    """Render a human-readable Markdown summary for one proposal folder."""
    lines: list[str] = []

    lines.append(f"# {metadata.canonical_proposal_name}")
    lines.append("")
    lines.append(f"**Proposal ID:** {metadata.proposal_id}  ")
    parts = [
        f"**Year:** {metadata.year_folder}",
        f"**Agency:** {metadata.agency}",
        f"**Program:** {metadata.program}",
    ]
    if metadata.phase:
        parts.append(f"**Phase:** {metadata.phase}")
    lines.append(" | ".join(parts) + "  ")
    lines.append(f"**Status:** {metadata.status} | **Award Status:** {metadata.award_status}  ")
    if metadata.submission_date:
        lines.append(f"**Submission Date:** {metadata.submission_date}  ")
    if metadata.topic_number:
        lines.append(f"**Topic Number:** {metadata.topic_number}  ")
    if metadata.solicitation_number:
        lines.append(f"**Solicitation:** {metadata.solicitation_number}  ")
    lines.append("")

    lines.append("---")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(metadata.folder_summary_short)
    lines.append("")
    if metadata.folder_summary_detailed:
        lines.append(metadata.folder_summary_detailed)
        lines.append("")

    if metadata.opportunity_context_summary:
        lines.append("## Opportunity Context")
        lines.append("")
        lines.append(metadata.opportunity_context_summary)
        lines.append("")

    if metadata.generated_response_summary:
        lines.append("## Proposal Response Summary")
        lines.append("")
        lines.append(metadata.generated_response_summary)
        lines.append("")

    lines.append("## Document Counts")
    lines.append("")
    lines.append("| Category | Count |")
    lines.append("|---|---|")
    lines.append(f"| Included in clean set | {metadata.included_document_count} |")
    lines.append(f"| Excluded | {metadata.excluded_document_count} |")
    lines.append(f"| Manual review required | {metadata.manual_review_count} |")
    lines.append(f"| Open critical questions | {metadata.open_critical_questions} |")
    lines.append("")

    if metadata.key_documents:
        lines.append("## Key Documents")
        lines.append("")
        for kd in metadata.key_documents:
            role_label = str(kd.document_role) if kd.document_role else "unknown"
            filename = kd.file_name_original or kd.document_id
            status = "included" if kd.include_in_clean_set else "excluded"
            lines.append(f"- **{role_label}**: {filename} ({status})")
        lines.append("")

    if metadata.technical_focus:
        lines.append("## Technical Focus")
        lines.append("")
        lines.append(", ".join(metadata.technical_focus))
        lines.append("")

    if metadata.partners:
        lines.append("## Partners")
        lines.append("")
        for partner in metadata.partners:
            lines.append(f"- {partner}")
        lines.append("")

    lines.append("## Readiness")
    lines.append("")
    lines.append(f"- Ready for clean set: {'Yes' if metadata.ready_for_clean_set else 'No'}")
    lines.append(f"- Ready for future S3: {'Yes' if metadata.ready_for_future_s3 else 'No'}")
    lines.append("")

    lines.append("## Tracker")
    lines.append("")
    lines.append(f"- Match status: {metadata.tracker_match_status}")
    if metadata.tracker_disagreements:
        lines.append(f"- Disagreements: {len(metadata.tracker_disagreements)}")
        for d in metadata.tracker_disagreements:
            lines.append(
                f"  - `{d.get('field')}`: folder=`{d.get('folder_value')}` "
                f"tracker=`{d.get('tracker_value')}`"
            )
    else:
        lines.append("- Disagreements: none")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def _consensus_str(values: list[str | None], *, fallback: str, ignore: set[str]) -> str:
    candidates = [v for v in values if v and v not in ignore]
    if not candidates:
        return fallback
    most_common, _ = Counter(candidates).most_common(1)[0]
    return most_common


def _consensus_enum(values: list[str], *, default: str, ignore: set[str]) -> str:
    candidates = [v for v in values if v not in ignore]
    if not candidates:
        return default
    most_common, _ = Counter(candidates).most_common(1)[0]
    return most_common


def _first_non_none(values: list[str | None]) -> str | None:
    return next((v for v in values if v is not None), None)


def _union_lists(lists: list[list[str]]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for items in lists:
        for item in items:
            if item and item not in seen:
                seen.add(item)
                result.append(item)
    return result


# ---------------------------------------------------------------------------
# Key document selection
# ---------------------------------------------------------------------------


def _identify_key_documents(documents: list[DocumentMetadata]) -> list[FolderKeyDocument]:
    docs_by_role: dict[DocumentRole, DocumentMetadata] = {}
    for doc in documents:
        role = doc.document_identity.document_role
        if role not in docs_by_role:
            docs_by_role[role] = doc
        elif (
            doc.inclusion.include_in_clean_set
            and not docs_by_role[role].inclusion.include_in_clean_set
        ):
            # prefer included over excluded
            docs_by_role[role] = doc

    seen_ids: set[str] = set()
    result: list[FolderKeyDocument] = []

    for role in _KEY_DOCUMENT_ROLES:
        if len(result) >= _MAX_KEY_DOCUMENTS:
            break
        role_doc = docs_by_role.get(role)
        if role_doc and role_doc.document_id not in seen_ids:
            seen_ids.add(role_doc.document_id)
            result.append(
                FolderKeyDocument(
                    document_id=role_doc.document_id,
                    file_name_original=role_doc.system.file_name_original,
                    document_role=role,
                    include_in_clean_set=role_doc.inclusion.include_in_clean_set,
                )
            )

    # append high-priority docs not already listed
    for doc in documents:
        if len(result) >= _MAX_KEY_DOCUMENTS:
            break
        if (
            str(doc.inclusion.rag_priority) == RagPriority.high.value
            and doc.document_id not in seen_ids
        ):
            seen_ids.add(doc.document_id)
            result.append(
                FolderKeyDocument(
                    document_id=doc.document_id,
                    file_name_original=doc.system.file_name_original,
                    document_role=doc.document_identity.document_role,
                    include_in_clean_set=doc.inclusion.include_in_clean_set,
                )
            )

    return result


# ---------------------------------------------------------------------------
# Tracker folder-level application
# ---------------------------------------------------------------------------


def _apply_tracker_to_folder(
    *,
    proposal_branch: str,
    tracker_rows: list[TrackerRow],
    canonical_proposal_name: str,
    submission_date: str | None,
    status_str: str,
    award_status: str,
) -> tuple[
    TrackerMatchStatus, str, str | None, str | None, str | None, str, str, list[dict[str, Any]]
]:
    """Match and apply tracker high-authority fields at folder level.

    Returns:
        (match_status, canonical_proposal_name, submission_date,
         selection_notification_date, award_date, status_str, award_status, disagreements)
    """
    match_result = match_tracker_row(
        proposal_branch,
        tracker_rows,
        canonical_proposal_name=canonical_proposal_name,
    )

    selection_notification_date: str | None = None
    award_date: str | None = None
    disagreements: list[dict[str, Any]] = []

    if match_result.status != TrackerMatchStatus.matched or match_result.tracker_row is None:
        return (
            match_result.status,
            canonical_proposal_name,
            submission_date,
            selection_notification_date,
            award_date,
            status_str,
            award_status,
            disagreements,
        )

    row = match_result.tracker_row.values

    tracker_name = row.get("proposal_name")
    if tracker_name and tracker_name != canonical_proposal_name:
        disagreements.append(
            {
                "field": "canonical_proposal_name",
                "folder_value": canonical_proposal_name,
                "tracker_value": tracker_name,
                "source": "tracker",
            }
        )
        canonical_proposal_name = tracker_name

    tracker_submission = row.get("submission_date")
    if tracker_submission:
        if submission_date and submission_date != tracker_submission:
            disagreements.append(
                {
                    "field": "submission_date",
                    "folder_value": submission_date,
                    "tracker_value": tracker_submission,
                    "source": "tracker",
                }
            )
        submission_date = tracker_submission

    selection_notification_date = row.get("selection_notification_date")
    award_date = row.get("award_date")

    normalized_status = _normalize_status(row.get("status"))
    if normalized_status and normalized_status != status_str:
        disagreements.append(
            {
                "field": "status",
                "folder_value": status_str,
                "tracker_value": normalized_status,
                "source": "tracker",
            }
        )
        status_str = normalized_status

    tracker_award = row.get("award_status") or row.get("result")
    if tracker_award:
        if award_status != tracker_award:
            disagreements.append(
                {
                    "field": "award_status",
                    "folder_value": award_status,
                    "tracker_value": tracker_award,
                    "source": "tracker",
                }
            )
        award_status = tracker_award

    return (
        match_result.status,
        canonical_proposal_name,
        submission_date,
        selection_notification_date,
        award_date,
        status_str,
        award_status,
        disagreements,
    )


# ---------------------------------------------------------------------------
# Summary generation
# ---------------------------------------------------------------------------


def _build_summaries(
    documents: list[DocumentMetadata],
    *,
    canonical_proposal_name: str,
    agency: str,
    program: str,
    status_str: str,
    included_docs: list[DocumentMetadata],
    use_mock: bool,
    config: Any,
) -> tuple[str, str, str, str]:
    """Return (folder_summary_short, folder_summary_detailed, opp_context, gen_response)."""
    if use_mock:
        return _build_mock_summaries(
            documents=documents,
            canonical_proposal_name=canonical_proposal_name,
            agency=agency,
            program=program,
            status_str=status_str,
            included_docs=included_docs,
        )
    return _build_bedrock_summaries(
        documents=documents,
        canonical_proposal_name=canonical_proposal_name,
        agency=agency,
        program=program,
        status_str=status_str,
        included_docs=included_docs,
        config=config,
    )


def _build_mock_summaries(
    *,
    documents: list[DocumentMetadata],
    canonical_proposal_name: str,
    agency: str,
    program: str,
    status_str: str,
    included_docs: list[DocumentMetadata],
) -> tuple[str, str, str, str]:
    n = len(included_docs)
    folder_summary_short = (
        f"This folder contains {n} included document(s) for the {program} proposal "
        f"'{canonical_proposal_name}' submitted to {agency}. Status: {status_str}."
    )

    detail_parts: list[str] = []
    for doc in included_docs[:_SUMMARY_DETAIL_MAX_DOCS]:
        short = doc.content.summary_short.strip()
        if short:
            title = doc.document_identity.canonical_document_title or doc.system.file_name_original
            detail_parts.append(f"**{title}**: {short}")
    folder_summary_detailed = "\n\n".join(detail_parts)

    opp_parts = [
        doc.opportunity_treatment.useful_context_summary.strip()
        for doc in documents
        if doc.opportunity_treatment.useful_context_summary.strip()
    ]
    opportunity_context_summary = " ".join(opp_parts)[:_SUMMARY_EXCERPT_CHARS]

    gen_parts = [
        doc.content.summary_short.strip()
        for doc in included_docs
        if str(doc.document_identity.origin_type) == OriginType.generated_response.value
        and doc.content.summary_short.strip()
    ]
    generated_response_summary = " ".join(gen_parts)[:_SUMMARY_EXCERPT_CHARS]

    return (
        folder_summary_short,
        folder_summary_detailed,
        opportunity_context_summary,
        generated_response_summary,
    )


def _build_bedrock_summaries(
    *,
    documents: list[DocumentMetadata],
    canonical_proposal_name: str,
    agency: str,
    program: str,
    status_str: str,
    included_docs: list[DocumentMetadata],
    config: Any,
) -> tuple[str, str, str, str]:
    """Call Bedrock once per folder to generate narrative summaries."""
    from proposal_ingest.bedrock_client import (
        call_converse_with_text,
        create_bedrock_runtime_client,
    )

    doc_lines: list[str] = []
    for i, doc in enumerate(included_docs[:20], start=1):
        role = str(doc.document_identity.document_role)
        fname = doc.system.file_name_original
        short = doc.content.summary_short.strip() or "(no summary)"
        doc_lines.append(f"{i}. [{role}] {fname}: {short}")

    prompt = textwrap.dedent(f"""
        You are summarizing a proposal folder for an internal RAG system.

        Proposal: {canonical_proposal_name}
        Agency: {agency}, Program: {program}, Status: {status_str}
        Included documents ({len(included_docs)}):
        {chr(10).join(doc_lines)}

        Return a JSON object with exactly these keys:
        {{
          "folder_summary_short": "2-3 sentence summary of this proposal folder.",
          "folder_summary_detailed": "3-5 paragraph detailed summary.",
          "opportunity_context_summary": "Brief summary of the opportunity/RFP if documents describe it, else empty string.",
          "generated_response_summary": "Brief summary of the proposal response content, else empty string."
        }}
        Return only the JSON object with no other text.
    """).strip()

    model_id = config.bedrock.model_id if config else "claude-opus-4-6"

    try:
        client = create_bedrock_runtime_client(config)
        raw_text, _ = call_converse_with_text(
            client,
            model_id=model_id,
            system_prompt="You are a proposal archive summarization assistant.",
            user_prompt=prompt,
            max_tokens=1024,
            temperature=0.0,
        )
        parsed = json.loads(raw_text)
        return (
            parsed.get("folder_summary_short", ""),
            parsed.get("folder_summary_detailed", ""),
            parsed.get("opportunity_context_summary", ""),
            parsed.get("generated_response_summary", ""),
        )
    except Exception:
        logger.exception("Bedrock folder summary call failed; falling back to mock summaries")
        return _build_mock_summaries(
            documents=documents,
            canonical_proposal_name=canonical_proposal_name,
            agency=agency,
            program=program,
            status_str=status_str,
            included_docs=included_docs,
        )
