"""Private seed-family extraction coverage and deterministic inspection sampling.

The manifest contains IDs and counts only. Operators inspect actual passages in the
authenticated UI and keep judgments and source excerpts in private evaluation storage.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any

from . import models as m


def audit_collection(collection_id, *, per_family: int = 5) -> dict:
    if not 1 <= per_family <= 100:
        raise ValueError("per_family must be between 1 and 100")
    families = m.VersionFamily.objects.filter(proposal__collection_id=collection_id).order_by("id")
    report: dict[str, Any] = {"collection_id": str(collection_id), "families": [], "totals": {}}
    totals: Counter[str] = Counter()
    for family in families:
        sources = m.SourceItem.objects.filter(proposalmembership__family=family).distinct()
        versions = list(
            m.SourceVersion.objects.filter(source__in=sources)
            .select_related("source", "blob")
            .order_by("id")
        )
        rows = []
        counts: Counter[str] = Counter()
        for version in versions:
            latest = m.ExtractionRun.objects.filter(version=version).order_by("-number").first()
            state = latest.state if latest else "unattempted"
            counts[state] += 1
            totals[state] += 1
            units = m.ExtractedUnit.objects.filter(extraction_run=latest) if latest else None
            figures = m.FigureAsset.objects.filter(run=latest) if latest else None
            unit_count = units.count() if units is not None else 0
            figure_count = figures.count() if figures is not None else 0
            warning_count = (
                len(latest.warnings)
                + sum(len(warnings) for warnings in units.values_list("warnings", flat=True))
                if latest and units is not None
                else 0
            )
            counts["units"] += unit_count
            counts["figures"] += figure_count
            counts["warnings"] += warning_count
            suffix = (version.observed_path or version.source.display_path).rsplit(".", 1)[-1]
            rows.append(
                {
                    "source_version_id": str(version.id),
                    "run_id": str(latest.id) if latest else None,
                    "format": suffix.casefold(),
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
            priority = 0 if row["state"] != "succeeded" else (1 if row["figure_count"] else 2)
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
