"""Read-only year inventory and forecast; this module never dispatches work."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections import Counter
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Iterable

from .source_sync import disposition


@dataclass(frozen=True)
class InventoryItem:
    path: str
    size: int
    disposition: str
    reason: str


@dataclass(frozen=True)
class ProposalInventory:
    name: str
    items: tuple[InventoryItem, ...]
    complete: bool
    error: str = ""


@dataclass(frozen=True)
class YearInventory:
    year: int
    proposals: tuple[ProposalInventory, ...]
    complete: bool
    error: str = ""


@dataclass(frozen=True)
class ListingPage:
    items: tuple[InventoryItem, ...]
    next_cursor: str | None
    complete: bool


def _classified(path: str, size: int, *, folder: bool, link: bool) -> InventoryItem:
    candidate = SimpleNamespace(name=Path(path).name, path=path, is_folder=folder, is_link=link)
    state, reason = disposition(candidate)
    return InventoryItem(path, size, state, reason)


def inventory_local(year_root: Path, *, year: int) -> YearInventory:
    """Stat a year tree without opening files or following links."""
    root = Path(year_root)
    if root.name != str(year) or not root.is_dir():
        raise ValueError("The year root must be an existing named year directory")
    proposals = []
    try:
        with os.scandir(root) as entries:
            children = sorted(list(entries), key=lambda item: item.name)
    except OSError:
        return YearInventory(year, (), False, "year_listing_failed")
    for child in children:
        try:
            metadata = child.stat(follow_symlinks=False)
            if not stat.S_ISDIR(metadata.st_mode):
                proposals.append(ProposalInventory(child.name, (), False, "non_proposal_year_item"))
                continue
            items: list[InventoryItem] = []
            pending = [Path(child.path)]
            while pending:
                directory = pending.pop()
                with os.scandir(directory) as entries:
                    for entry in entries:
                        info = entry.stat(follow_symlinks=False)
                        relative = Path(entry.path).relative_to(child.path).as_posix()
                        folder = stat.S_ISDIR(info.st_mode)
                        link = stat.S_ISLNK(info.st_mode)
                        items.append(
                            _classified(
                                relative,
                                info.st_size if not folder else 0,
                                folder=folder,
                                link=link,
                            )
                        )
                        if folder:
                            pending.append(Path(entry.path))
            proposals.append(
                ProposalInventory(child.name, tuple(sorted(items, key=lambda row: row.path)), True)
            )
        except OSError:
            proposals.append(ProposalInventory(child.name, (), False, "proposal_listing_failed"))
    return YearInventory(year, tuple(proposals), all(row.complete for row in proposals))


def inventory_listed(
    year: int,
    roots: Iterable[str],
    list_page: Callable[[str, str | None], ListingPage],
    *,
    roots_complete: bool,
) -> YearInventory:
    """Accept checked pages from an injected scoped listing adapter."""
    proposals = []
    try:
        names = sorted(roots)
    except Exception:
        return YearInventory(year, (), False, "year_listing_failed")
    for name in names:
        try:
            items: list[InventoryItem] = []
            cursor = None
            seen = set()
            while True:
                page = list_page(name, cursor)
                items.extend(page.items)
                if page.complete:
                    proposals.append(ProposalInventory(name, tuple(items), True))
                    break
                if not page.next_cursor or page.next_cursor in seen:
                    raise ValueError("incomplete listing")
                seen.add(page.next_cursor)
                cursor = page.next_cursor
        except Exception:
            proposals.append(ProposalInventory(name, (), False, "proposal_listing_failed"))
    return YearInventory(
        year,
        tuple(proposals),
        roots_complete and all(row.complete for row in proposals),
        "" if roots_complete else "year_listing_incomplete",
    )


def plan_batches(
    inventory: YearInventory,
    *,
    observed_items: int,
    observed_accounted_usd: Decimal,
    observed_indexed_bytes: int,
    observed_monthly_index_usd: Decimal,
    setup_spent_usd: Decimal,
    current_monthly_usd: Decimal,
    max_items: int,
    max_cost_usd: Decimal,
) -> dict:
    """Forecast conservatively and group whole proposals; never execute a batch."""
    if not inventory.complete:
        return {"ready": False, "reason": "incomplete_inventory", "batches": []}
    if observed_items < 1 or observed_indexed_bytes < 1 or max_items < 1 or max_cost_usd <= 0:
        raise ValueError("Observed denominators and batch caps must be positive")
    if any(
        value < 0
        for value in (
            observed_accounted_usd,
            observed_monthly_index_usd,
            setup_spent_usd,
            current_monthly_usd,
        )
    ):
        raise ValueError("Observed costs cannot be negative")
    unit_cost = observed_accounted_usd / observed_items
    storage_rate = observed_monthly_index_usd / observed_indexed_bytes
    proposals = []
    all_items = 0
    all_bytes = 0
    for proposal in inventory.proposals:
        actionable = [item for item in proposal.items if item.disposition == "awaiting_extraction"]
        item_count = len(actionable)
        byte_count = sum(item.size for item in actionable)
        all_items += item_count
        all_bytes += byte_count
        proposals.append((proposal.name, item_count, byte_count))
    fingerprint = hashlib.sha256(json.dumps(asdict(inventory), sort_keys=True).encode()).hexdigest()
    batches: list[dict] = []
    held = []
    names: list[str] = []
    count = 0
    estimate = Decimal("0")
    for name, item_count, _ in proposals:
        cost = unit_cost * item_count
        if item_count > max_items or cost > max_cost_usd:
            held.append({"proposal": name, "reason": "proposal_exceeds_batch_cap"})
            continue
        if names and (count + item_count > max_items or estimate + cost > max_cost_usd):
            batches.append(
                {
                    "checkpoint": f"{fingerprint[:16]}:{len(batches) + 1}",
                    "proposals": names,
                    "items": count,
                    "estimated_usd": str(estimate),
                }
            )
            names, count, estimate = [], 0, Decimal("0")
        names.append(name)
        count += item_count
        estimate += cost
    if names:
        batches.append(
            {
                "checkpoint": f"{fingerprint[:16]}:{len(batches) + 1}",
                "proposals": names,
                "items": count,
                "estimated_usd": str(estimate),
            }
        )
    incremental = unit_cost * all_items
    monthly_index = storage_rate * all_bytes
    return {
        "ready": False,
        "reason": "over_cap_proposals" if held else "awaiting_owner_approval",
        "inventory_fingerprint": fingerprint,
        "actionable_items": all_items,
        "disposition_counts": dict(
            Counter(item.disposition for proposal in inventory.proposals for item in proposal.items)
        ),
        "extraction_exceptions": sum(
            item.disposition == "awaiting_conversion"
            for proposal in inventory.proposals
            for item in proposal.items
        ),
        "forecast_incremental_usd": str(incremental),
        "forecast_monthly_index_usd": str(monthly_index),
        "projected_setup_total_usd": str(setup_spent_usd + incremental),
        "projected_monthly_total_usd": str(current_monthly_usd + monthly_index),
        "within_setup_ceiling": setup_spent_usd + incremental <= Decimal("500"),
        "within_monthly_ceiling": current_monthly_usd + monthly_index <= Decimal("100"),
        "batches": batches,
        "held": held,
    }
