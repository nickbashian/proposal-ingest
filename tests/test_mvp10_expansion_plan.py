"""Offline MVP-10 inventory and planning contracts; no source bytes or providers."""

import json
import os
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from proposal_app.expansion_plan import (
    InventoryItem,
    ListingPage,
    inventory_listed,
    inventory_local,
    plan_batches,
)


def test_local_year_inventory_is_recursive_metadata_only(tmp_path, monkeypatch):
    root = tmp_path / "2025"
    first = root / "First" / "nested"
    first.mkdir(parents=True)
    (first / "result.pdf").write_bytes(b"private bytes")
    (first / "old.doc").write_bytes(b"legacy")
    (root / "Second").mkdir()
    (root / "Second" / "notes.txt").write_text("confidential")
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        if Path(path).is_relative_to(root):
            raise AssertionError("Source file bytes were opened")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    inventory = inventory_local(root, year=2025)
    assert inventory.complete
    assert len(inventory.proposals) == 2
    states = {
        item.path: item.disposition for proposal in inventory.proposals for item in proposal.items
    }
    assert states["nested/result.pdf"] == "awaiting_extraction"
    assert states["nested/old.doc"] == "awaiting_conversion"
    plan = plan_batches(
        inventory,
        observed_items=2,
        observed_accounted_usd=Decimal("0.40"),
        observed_indexed_bytes=100,
        observed_monthly_index_usd=Decimal("0.10"),
        setup_spent_usd=Decimal("499"),
        current_monthly_usd=Decimal("99"),
        max_items=1,
        max_cost_usd=Decimal("0.25"),
    )
    assert plan["actionable_items"] == 2
    assert plan["extraction_exceptions"] == 1
    assert plan["forecast_incremental_usd"] == "0.40"
    assert plan["within_setup_ceiling"]
    assert plan["within_monthly_ceiling"]
    assert len(plan["batches"]) == 2
    assert all(batch["items"] <= 1 for batch in plan["batches"])
    assert plan["reason"] == "awaiting_owner_approval"


def test_incomplete_listing_blocks_batch_plan(tmp_path, monkeypatch):
    root = tmp_path / "2025" / "Proposal"
    root.mkdir(parents=True)
    original_scandir = os.scandir

    def failed_scandir(path):
        if Path(path) == root:
            raise PermissionError("private path should not appear in report")
        return original_scandir(path)

    monkeypatch.setattr(os, "scandir", failed_scandir)
    inventory = inventory_local(root.parent, year=2025)
    assert not inventory.complete
    assert inventory.proposals[0].error == "proposal_listing_failed"
    assert (
        plan_batches(
            inventory,
            observed_items=1,
            observed_accounted_usd=Decimal("1"),
            observed_indexed_bytes=1,
            observed_monthly_index_usd=Decimal("1"),
            setup_spent_usd=Decimal("0"),
            current_monthly_usd=Decimal("0"),
            max_items=1,
            max_cost_usd=Decimal("1"),
        )["batches"]
        == []
    )


def test_injected_listing_requires_complete_pages():
    item = InventoryItem("x.pdf", 10, "awaiting_extraction", "supported_format")
    incomplete = inventory_listed(
        2025,
        ["Family"],
        lambda name, cursor: ListingPage((item,), "repeat", False),
        roots_complete=True,
    )
    assert not incomplete.complete
    complete = inventory_listed(
        2025,
        ["Family"],
        lambda name, cursor: ListingPage((item,), None, True),
        roots_complete=True,
    )
    assert complete.complete
    assert not inventory_listed(
        2025,
        ["Family"],
        lambda name, cursor: ListingPage((item,), None, True),
        roots_complete=False,
    ).complete


def test_over_cap_proposal_is_held_whole(tmp_path):
    root = tmp_path / "2025" / "Large"
    root.mkdir(parents=True)
    for number in range(3):
        (root / f"{number}.pdf").write_bytes(b"x")
    plan = plan_batches(
        inventory_local(root.parent, year=2025),
        observed_items=1,
        observed_accounted_usd=Decimal("1"),
        observed_indexed_bytes=1,
        observed_monthly_index_usd=Decimal("0"),
        setup_spent_usd=Decimal("0"),
        current_monthly_usd=Decimal("0"),
        max_items=2,
        max_cost_usd=Decimal("2"),
    )
    assert not plan["ready"]
    assert plan["batches"] == []
    assert plan["held"][0]["reason"] == "proposal_exceeds_batch_cap"


def test_command_writes_private_plan_outside_source_and_never_overwrites(tmp_path):
    root = tmp_path / "2025"
    proposal = root / "A"
    proposal.mkdir(parents=True)
    (proposal / "a.pdf").write_bytes(b"x")
    observed = tmp_path / "observed.json"
    observed.write_text(
        json.dumps(
            {
                "observed_items": 1,
                "observed_accounted_usd": "0.5",
                "observed_indexed_bytes": 1,
                "observed_monthly_index_usd": "0.01",
                "setup_spent_usd": "0",
                "current_monthly_usd": "0",
            }
        )
    )
    output = tmp_path / "private_evaluations" / "plan.json"
    arguments = [
        "--year-root",
        str(root),
        "--observed-costs",
        str(observed),
        "--max-items",
        "2",
        "--max-cost-usd",
        "1",
    ]
    call_command("plan_year_expansion", *arguments, "--output", str(output))
    report = json.loads(output.read_text())
    assert report["plan"]["reason"] == "awaiting_owner_approval"
    with pytest.raises(CommandError, match="already exists"):
        call_command("plan_year_expansion", *arguments, "--output", str(output))
    with pytest.raises(CommandError, match="outside"):
        call_command("plan_year_expansion", *arguments, "--output", str(root / "plan.json"))
