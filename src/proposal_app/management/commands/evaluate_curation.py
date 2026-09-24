"""Run a bounded labeled comparison; print only aggregate metrics and run ID."""

import json
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from proposal_app import model_evaluation as evaluation


class FixtureAdapter:
    live = False
    estimated_cost_usd = Decimal("0")

    def __init__(self, route, predictions):
        self.route = route
        self.predictions = predictions

    def available(self):
        return True

    def predict(self, case):
        answer = self.predictions[case.key][self.route]
        return evaluation.Prediction(
            answer.get("label"),
            answer.get("confidence"),
            answer.get("latency_ms", 0),
            Decimal("0"),
            "synthetic-fixture-v1",
            answer.get("error"),
        )


class Command(BaseCommand):
    help = "Compare the three classification routes on identical labeled bounded cases."

    def add_arguments(self, parser):
        parser.add_argument("--collection", required=True)
        parser.add_argument("--user", required=True)
        parser.add_argument("--cases", type=Path, required=True)
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--mock", action="store_true")
        mode.add_argument("--live", action="store_true")
        parser.add_argument("--max-spend-usd", default="0")

    def handle(self, *args, **options):
        try:
            document = json.loads(options["cases"].read_text(encoding="utf-8"))
            cases = [evaluation.LabeledCase(**item) for item in document["cases"]]
            if options["mock"]:
                predictions = document["mock_predictions"]
                adapters = {
                    route: FixtureAdapter(route, predictions)
                    for route in ("baseline", "economical", "jev")
                }
            else:
                estimates = settings.APP["classification_estimate_usd_per_call"]
                adapters = {
                    "baseline": evaluation.BedrockChoiceAdapter(
                        "baseline", estimated_cost_usd=estimates["baseline"] or "0"
                    ),
                    "economical": evaluation.BedrockChoiceAdapter(
                        "economical", estimated_cost_usd=estimates["economical"] or "0"
                    ),
                    "jev": evaluation.JevChoiceAdapter(estimated_cost_usd=estimates["jev"] or "0"),
                }
            user = get_user_model().objects.get(username=options["user"])
            report = evaluation.compare(
                user,
                options["collection"],
                cases,
                adapters,
                max_spend_usd=options["max_spend_usd"],
                allow_live=options["live"],
                suite_revision=document["suite_revision"],
            )
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise CommandError(
                "Invalid evaluation input or unavailable route: " + str(exc)
            ) from exc
        # No source excerpt, prompt, or raw provider response reaches stdout.
        self.stdout.write(
            json.dumps(
                {
                    "run_id": report["run_id"],
                    "metrics": {
                        route: report[route]["metrics"]
                        for route in ("baseline", "economical", "jev")
                    },
                },
                indent=2,
            )
        )
