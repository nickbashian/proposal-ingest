"""Private seed-family extraction coverage and deterministic inspection sampling.

The manifest contains IDs and counts only. Operators inspect actual passages in the
authenticated UI and keep judgments and source excerpts in private evaluation storage.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Any

from django.db.models import Count

from . import models as m


def audit_collection(collection_id, *, per_family: int = 5) -> dict:
    if not 1 <= per_family <= 100:
        raise ValueError("per_family must be between 1 and 100")
    families = list(
        m.VersionFamily.objects.filter(proposal__collection_id=collection_id).order_by("id")
    )
    report: dict[str, Any] = {"collection_id": str(collection_id), "families": [], "totals": {}}
    totals: Counter[str] = Counter()
    counted_versions = set()
    membership_rows = m.ProposalMembership.objects.filter(family__in=families).values_list(
        "family_id", "source_id"
    )
    sources_by_family: dict = {}
    for family_id, source_id in membership_rows:
        sources_by_family.setdefault(family_id, set()).add(source_id)
    source_ids = set().union(*sources_by_family.values()) if sources_by_family else set()
    all_versions = list(
        m.SourceVersion.objects.filter(source_id__in=source_ids)
        .select_related("source", "blob")
        .order_by("id")
    )
    latest_by_version: dict[Any, m.ExtractionRun] = {}
    for run in m.ExtractionRun.objects.filter(version__in=all_versions).order_by(
        "version_id", "-number"
    ):
        latest_by_version.setdefault(run.version_id, run)
    run_ids = [run.id for run in latest_by_version.values()]
    unit_counts = dict(
        m.ExtractedUnit.objects.filter(extraction_run_id__in=run_ids)
        .values("extraction_run_id")
        .annotate(total=Count("id"))
        .values_list("extraction_run_id", "total")
    )
    figure_counts = dict(
        m.FigureAsset.objects.filter(run_id__in=run_ids)
        .values("run_id")
        .annotate(total=Count("id"))
        .values_list("run_id", "total")
    )
    unit_warnings: Counter = Counter()
    for run_id, warnings in m.ExtractedUnit.objects.filter(
        extraction_run_id__in=run_ids
    ).values_list("extraction_run_id", "warnings"):
        unit_warnings[run_id] += len(warnings)
    for family in families:
        versions = [
            version
            for version in all_versions
            if version.source_id in sources_by_family.get(family.id, set())
        ]
        rows = []
        counts: Counter[str] = Counter()
        for version in versions:
            latest = latest_by_version.get(version.id)
            state = latest.state if latest else "unattempted"
            counts[state] += 1
            if version.id not in counted_versions:
                totals[state] += 1
                counted_versions.add(version.id)
            unit_count = unit_counts.get(latest.id, 0) if latest else 0
            figure_count = figure_counts.get(latest.id, 0) if latest else 0
            warning_count = len(latest.warnings) + unit_warnings[latest.id] if latest else 0
            counts["units"] += unit_count
            counts["figures"] += figure_count
            counts["warnings"] += warning_count
            suffix = Path(version.observed_path or version.source.display_path).suffix.lstrip(".")
            rows.append(
                {
                    "source_version_id": str(version.id),
                    "run_id": str(latest.id) if latest else None,
                    "format": suffix.casefold() or "none",
                    "state": state,
                    "reason": latest.reason if latest else "not_attempted",
                    "unit_count": unit_count,
                    "figure_count": figure_count,
                    "warning_count": warning_count,
                    "inspector_path": f"/sources/{version.id}/inspect/",
                }
            )

        # Surface failures and figures first, then deterministic spread over the rest.
        def rank(row):
            priority = (
                0
                if row["state"] in {"failed", "scanned"}
                else 1 if row["figure_count"] else 2 if row["state"] == "unattempted" else 3
            )
            tie_break = hashlib.sha256(row["source_version_id"].encode()).hexdigest()
            return priority, tie_break

        report["families"].append(
            {
                "family_id": str(family.id),
                "version_count": len(rows),
                "counts": dict(sorted(counts.items())),
                "sample": sorted(rows, key=rank)[:per_family],
            }
        )
    report["totals"] = dict(sorted(totals.items()))
    return report
