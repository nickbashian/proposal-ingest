"""Grants tracker ingestion, normalization, matching, and metadata overrides."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from proposal_ingest.path_utils import short_hash
from proposal_ingest.schemas import DocumentMetadata, ProposalStatus, TrackerMatchStatus

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_TRACKER_MATCH_MIN_CONFIDENCE = 0.35
_TRACKER_MATCH_AMBIGUITY_DELTA = 0.05

_COLUMN_ALIASES = {
    "grant_org": {
        "grant_org",
        "grant_organization",
        "organization",
        "org",
    },
    "grant_number": {
        "grant_number",
        "grant_no",
        "grant_id",
        "solicitation_number",
        "topic_number",
        "number",
    },
    "proposal_name": {
        "proposal_name",
        "name",
        "grant_name",
        "project_name",
        "proposal",
    },
    "agency": {
        "agency",
        "sponsor",
        "customer",
    },
    "program": {
        "program",
        "program_name",
    },
    "issue_date": {
        "issue_date",
        "released_date",
        "release_date",
    },
    "concept_paper_due_date": {
        "concept_paper_due_date",
        "concept_due_date",
    },
    "concept_paper_notification_date": {
        "concept_paper_notification_date",
        "concept_notification_date",
    },
    "submission_date": {
        "submission_date",
        "submission_due_date",
        "due_date",
        "proposal_due_date",
    },
    "selection_notification_date": {
        "selection_notification_date",
        "selection_date",
        "notification_date",
    },
    "award_date": {
        "award_date",
        "date_awarded",
    },
    "status": {
        "status",
        "proposal_status",
    },
    "award_status": {
        "award_status",
    },
    "result": {
        "result",
        "outcome",
    },
    "comments": {
        "comments",
        "comment",
        "notes",
    },
    "link": {
        "link",
        "url",
    },
}

_STATUS_ALIASES = {
    "draft": "drafted",
    "drafted": "drafted",
    "pre_submission": "drafted",
    "submitted": "submitted",
    "selected": "selected",
    "awarded": "awarded",
    "rejected": "rejected",
    "declined": "rejected",
    "pending": "pending",
    "active": "active",
    "completed": "completed",
}

_TRACKER_HIGH_AUTHORITY_FIELDS = {
    "submission_date",
    "selection_notification_date",
    "award_date",
    "status",
    "award_status",
    "result",
}


@dataclass(frozen=True)
class TrackerRow:
    """Normalized tracker row."""

    row_id: str
    values: dict[str, Any]

    @property
    def proposal_name(self) -> str:
        raw = self.values.get("proposal_name")
        return str(raw).strip() if raw is not None else ""


@dataclass(frozen=True)
class TrackerMatchResult:
    """Result of proposal-to-tracker matching."""

    status: TrackerMatchStatus
    confidence: float
    tracker_row: TrackerRow | None = None
    candidate_row_ids: list[str] | None = None


def load_tracker_rows(
    tracker_path: Path | str,
    *,
    sheet_name: str | None = None,
    header_row: int = 0,
) -> list[TrackerRow]:
    """Load and normalize tracker rows from an Excel workbook.

    When ``sheet_name`` is provided, only that sheet is read.
    When ``sheet_name`` is ``None``, all sheets are read and concatenated.
    """
    path = Path(tracker_path).resolve()
    dataframe = pd.read_excel(path, sheet_name=sheet_name, header=header_row, dtype=object)
    if isinstance(dataframe, dict):
        rows: list[TrackerRow] = []
        for resolved_sheet, df in dataframe.items():
            rows.extend(_rows_from_dataframe(path, resolved_sheet, df))
        return rows
    resolved_sheet = sheet_name or "Sheet1"
    return _rows_from_dataframe(path, resolved_sheet, dataframe)


def write_tracker_rows_jsonl(rows: list[TrackerRow], run_dir: Path) -> Path:
    """Write normalized tracker rows to run_dir/tracker/tracker_rows.jsonl."""
    tracker_dir = run_dir / "tracker"
    tracker_dir.mkdir(parents=True, exist_ok=True)
    out_path = tracker_dir / "tracker_rows.jsonl"
    with out_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps({"row_id": row.row_id, **row.values}, sort_keys=True))
            handle.write("\n")
    return out_path


def load_tracker_rows_jsonl(path: Path) -> list[TrackerRow]:
    """Load tracker rows from a normalized JSONL cache file."""
    rows: list[TrackerRow] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            row_id = str(payload.pop("row_id"))
            rows.append(TrackerRow(row_id=row_id, values=payload))
    return rows


def match_tracker_row(
    proposal_branch_name: str,
    tracker_rows: list[TrackerRow],
    *,
    canonical_proposal_name: str | None = None,
) -> TrackerMatchResult:
    """Match a proposal branch to the most likely tracker row using token overlap."""
    if not tracker_rows:
        return TrackerMatchResult(status=TrackerMatchStatus.unmatched, confidence=0.0)

    hints = [proposal_branch_name]
    if canonical_proposal_name:
        hints.append(canonical_proposal_name)
    hint_tokens = _name_tokens(" ".join(hints))
    if not hint_tokens:
        return TrackerMatchResult(status=TrackerMatchStatus.unmatched, confidence=0.0)

    scored: list[tuple[float, TrackerRow]] = []
    for row in tracker_rows:
        row_tokens = _name_tokens(row.proposal_name)
        if not row_tokens:
            continue
        score = len(hint_tokens & row_tokens) / len(hint_tokens | row_tokens)
        scored.append((score, row))

    if not scored:
        return TrackerMatchResult(status=TrackerMatchStatus.unmatched, confidence=0.0)

    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_row = scored[0]
    if best_score < _TRACKER_MATCH_MIN_CONFIDENCE:
        return TrackerMatchResult(status=TrackerMatchStatus.unmatched, confidence=best_score)

    contenders = [
        row for score, row in scored if abs(score - best_score) < _TRACKER_MATCH_AMBIGUITY_DELTA
    ]
    if len(contenders) > 1:
        return TrackerMatchResult(
            status=TrackerMatchStatus.ambiguous,
            confidence=best_score,
            candidate_row_ids=[row.row_id for row in contenders],
        )

    return TrackerMatchResult(
        status=TrackerMatchStatus.matched,
        confidence=best_score,
        tracker_row=best_row,
        candidate_row_ids=[best_row.row_id],
    )


def apply_tracker_overrides(
    metadata: DocumentMetadata,
    match_result: TrackerMatchResult,
) -> DocumentMetadata:
    """Apply high-authority tracker fields and record disagreements."""
    data = metadata.model_dump(mode="json")
    tracker_matching = data.setdefault("tracker_matching", {})
    disagreements: list[dict[str, Any]] = list(tracker_matching.get("tracker_disagreements", []))

    tracker_matching["tracker_match_status"] = match_result.status.value
    tracker_matching["tracker_match_confidence"] = float(match_result.confidence)

    if match_result.status != TrackerMatchStatus.matched or match_result.tracker_row is None:
        tracker_matching["tracker_row_id"] = None
        tracker_matching["tracker_disagreements"] = disagreements
        return DocumentMetadata.model_validate(data)

    tracker_matching["tracker_row_id"] = match_result.tracker_row.row_id
    row = match_result.tracker_row.values
    context = data["proposal_context"]

    _record_disagreement(
        disagreements,
        field="canonical_proposal_name",
        ai_value=context.get("canonical_proposal_name"),
        tracker_value=row.get("proposal_name"),
    )

    _override_if_present(context, row, disagreements, "submission_date", "submission_date")
    _override_if_present(
        context,
        row,
        disagreements,
        "selection_notification_date",
        "response_date",
    )

    normalized_status = _normalize_status(row.get("status"))
    if normalized_status is not None:
        _record_disagreement(
            disagreements,
            field="status",
            ai_value=context.get("status"),
            tracker_value=normalized_status,
        )
        context["status"] = normalized_status

    tracker_award_status = row.get("award_status") or row.get("result")
    if tracker_award_status:
        _record_disagreement(
            disagreements,
            field="award_status",
            ai_value=context.get("award_status"),
            tracker_value=tracker_award_status,
        )
        context["award_status"] = tracker_award_status

    tracker_matching["tracker_disagreements"] = disagreements
    return DocumentMetadata.model_validate(data)


def _rows_from_dataframe(path: Path, sheet_name: str, dataframe: pd.DataFrame) -> list[TrackerRow]:
    normalized_columns = [_normalize_column_name(str(column)) for column in dataframe.columns]
    dataframe.columns = normalized_columns
    rows: list[TrackerRow] = []
    for row_number, (_, row) in enumerate(dataframe.iterrows(), start=1):
        normalized_row = {
            str(key): _normalize_value(value)
            for key, value in row.to_dict().items()
            if not _is_missing_column_key(key) and str(key)
        }
        if not any(value not in (None, "") for value in normalized_row.values()):
            continue
        row_id = _build_row_id(sheet_name, row_number, normalized_row)
        rows.append(TrackerRow(row_id=row_id, values=normalized_row))
    return rows


def _normalize_column_name(raw: str) -> str:
    compact = _NON_ALNUM_RE.sub("_", raw.strip().lower()).strip("_")
    if not compact:
        return "unknown_column"
    for canonical, aliases in _COLUMN_ALIASES.items():
        if compact in aliases:
            return canonical
    return compact


def _is_missing_column_key(key: Any) -> bool:
    if key is None:
        return True
    if isinstance(key, float):
        return pd.isna(key)
    return False


def _normalize_value(value: Any) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


def _build_row_id(sheet_name: str, row_index: int, values: dict[str, Any]) -> str:
    anchor = (
        f"{sheet_name}:{row_index}:"
        f"{values.get('proposal_name') or values.get('grant_number') or ''}"
    )
    return f"trk_{short_hash(anchor, length=12)}"


def _name_tokens(value: str) -> set[str]:
    return {token for token in _NON_ALNUM_RE.split(value.lower()) if len(token) > 1}


def _normalize_status(value: Any) -> str | None:
    if value is None:
        return None
    normalized = _NON_ALNUM_RE.sub("_", str(value).strip().lower()).strip("_")
    mapped = _STATUS_ALIASES.get(normalized)
    if mapped is None:
        return None
    if mapped not in {status.value for status in ProposalStatus}:
        return None
    return mapped


def _override_if_present(
    context: dict[str, Any],
    row: dict[str, Any],
    disagreements: list[dict[str, Any]],
    row_field: str,
    context_field: str,
) -> None:
    tracker_value = row.get(row_field)
    if not tracker_value:
        return
    _record_disagreement(
        disagreements,
        field=context_field,
        ai_value=context.get(context_field),
        tracker_value=tracker_value,
    )
    if row_field in _TRACKER_HIGH_AUTHORITY_FIELDS:
        context[context_field] = tracker_value


def _record_disagreement(
    disagreements: list[dict[str, Any]],
    *,
    field: str,
    ai_value: Any,
    tracker_value: Any,
) -> None:
    if tracker_value in (None, ""):
        return
    if _normalize_compare(ai_value) == _normalize_compare(tracker_value):
        return
    disagreements.append(
        {
            "field": field,
            "ai_value": ai_value,
            "tracker_value": tracker_value,
            "source": "tracker",
        }
    )


def _normalize_compare(value: Any) -> str:
    if value is None:
        return ""
    return _NON_ALNUM_RE.sub("", str(value).lower())
