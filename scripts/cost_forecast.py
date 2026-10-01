"""Calculate a gross deployment forecast from owner-verified unit prices.

The input contains prices and quantities, never account identifiers or source data.
Credits are displayed separately so they cannot disguise an over-budget design.
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from proposal_ingest.config import load_web_application_defaults

REQUIRED_MONTHLY_CATEGORIES = {
    "compute",
    "persistent_storage",
    "backup",
    "network_and_address",
    "object_storage",
    "managed_kb",
    "models",
    "secrets_and_logs",
    "dns",
}


def _money(value: object, label: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"{label} must be a finite nonnegative decimal") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"{label} must be a finite nonnegative decimal")
    return amount


def forecast(payload: dict, *, limits: dict | None = None) -> dict:
    """Require a complete priced scenario before returning budget comparisons."""
    if not isinstance(payload, dict) or not isinstance(payload.get("line_items"), list):
        raise ValueError("Forecast requires a line_items list")
    if not payload.get("region") or not payload.get("priced_at"):
        raise ValueError("Forecast requires a region and price verification date")
    totals = {"setup": Decimal("0"), "monthly": Decimal("0"), "tooling": Decimal("0")}
    categories = set()
    seen = set()
    for index, item in enumerate(payload["line_items"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Line item {index} must be an object")
        name = item.get("name")
        category = item.get("category")
        period = item.get("period")
        if not isinstance(name, str) or not name.strip() or name in seen:
            raise ValueError(f"Line item {index} needs a unique name")
        if not isinstance(category, str) or not category.strip():
            raise ValueError(f"Line item {index} needs a category")
        if not isinstance(period, str) or period not in totals:
            raise ValueError(f"Line item {index} needs a setup, monthly, or tooling period")
        seen.add(name)
        price = _money(item.get("unit_price_usd"), f"{name} unit_price_usd")
        quantity = _money(item.get("quantity"), f"{name} quantity")
        totals[period] += price * quantity
        if period == "monthly":
            categories.add(category)
    missing = REQUIRED_MONTHLY_CATEGORIES - categories
    if missing:
        raise ValueError("Missing monthly cost categories: " + ", ".join(sorted(missing)))
    credits = _money(payload.get("estimated_credits_usd", "0"), "estimated_credits_usd")
    config = limits or load_web_application_defaults()
    setup_limit = _money(config["setup_limit_usd"], "setup_limit_usd")
    monthly_limit = _money(config["monthly_limit_usd"], "monthly_limit_usd")
    return {
        "region": payload["region"],
        "priced_at": payload["priced_at"],
        "setup_gross_usd": str(totals["setup"]),
        "monthly_gross_usd": str(totals["monthly"]),
        "tooling_separate_usd": str(totals["tooling"]),
        "estimated_credits_usd": str(credits),
        "setup_within_limit": totals["setup"] <= setup_limit,
        "monthly_within_limit": totals["monthly"] <= monthly_limit,
        "monthly_target_met": totals["monthly"] <= Decimal("50"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Private forecast JSON with verified prices")
    args = parser.parse_args()
    try:
        report = forecast(json.loads(args.path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Forecast incomplete: {exc}\n")
    print(json.dumps(report, indent=2))
    return 0 if report["setup_within_limit"] and report["monthly_within_limit"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
