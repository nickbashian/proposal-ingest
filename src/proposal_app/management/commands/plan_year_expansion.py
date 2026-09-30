"""Write a private, metadata-only year inventory and proposed batches."""

import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from proposal_app.expansion_plan import inventory_local, plan_batches


class Command(BaseCommand):
    help = "Read-only local 2025 inventory and costed batch proposal; performs no ingestion."

    def add_arguments(self, parser):
        parser.add_argument("--year-root", required=True)
        parser.add_argument("--observed-costs", required=True)
        parser.add_argument("--output", required=True)
        parser.add_argument("--max-items", required=True, type=int)
        parser.add_argument("--max-cost-usd", required=True)

    def handle(self, *args, **options):
        root = Path(options["year_root"]).resolve()
        output = Path(options["output"]).resolve()
        if output.is_relative_to(root):
            raise CommandError("Output must stay outside the read-only source root")
        if output.exists():
            raise CommandError("Output already exists; choose a new private report path")
        try:
            observed = json.loads(Path(options["observed_costs"]).read_text(encoding="utf-8"))
            inventory = inventory_local(root, year=2025)
            plan = plan_batches(
                inventory,
                observed_items=int(observed["observed_items"]),
                observed_accounted_usd=Decimal(str(observed["observed_accounted_usd"])),
                observed_indexed_bytes=int(observed["observed_indexed_bytes"]),
                observed_monthly_index_usd=Decimal(str(observed["observed_monthly_index_usd"])),
                setup_spent_usd=Decimal(str(observed["setup_spent_usd"])),
                current_monthly_usd=Decimal(str(observed["current_monthly_usd"])),
                max_items=options["max_items"],
                max_cost_usd=Decimal(options["max_cost_usd"]),
            )
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
            raise CommandError("Inventory or observed-cost inputs are invalid") from exc
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with output.open("x", encoding="utf-8") as report:
                report.write(
                    json.dumps({"inventory": asdict(inventory), "plan": plan}, indent=2) + "\n"
                )
        except FileExistsError as exc:
            raise CommandError("Output already exists; choose a new private report path") from exc
        self.stdout.write(f"Wrote private offline plan to {output}")
        self.stdout.write(
            f"Inventory complete: {inventory.complete}; proposed batches: {len(plan['batches'])}"
        )
