"""Forecasts must expose gross spend and reject missing or invalid prices."""

import json
from decimal import Decimal

import pytest

from scripts.cost_forecast import REQUIRED_MONTHLY_CATEGORIES, forecast, main


def _scenario(monthly_price="1"):
    return {
        "region": "us-test-1",
        "priced_at": "2026-09-29",
        "estimated_credits_usd": "1000",
        "line_items": [
            {
                "name": category,
                "category": category,
                "period": "monthly",
                "unit_price_usd": monthly_price,
                "quantity": "1",
            }
            for category in sorted(REQUIRED_MONTHLY_CATEGORIES)
        ]
        + [
            {
                "name": "setup",
                "category": "setup_testing",
                "period": "setup",
                "unit_price_usd": "25",
                "quantity": "2",
            },
            {
                "name": "subscriptions",
                "category": "subscriptions",
                "period": "tooling",
                "unit_price_usd": "20",
                "quantity": "1",
            },
        ],
    }


def test_gross_cost_is_compared_before_credits_and_tooling_is_separate():
    report = forecast(
        _scenario(monthly_price="20"),
        limits={"setup_limit_usd": "500", "monthly_limit_usd": "100"},
    )
    assert Decimal(report["monthly_gross_usd"]) == 20 * len(REQUIRED_MONTHLY_CATEGORIES)
    assert report["estimated_credits_usd"] == "1000"
    assert report["tooling_separate_usd"] == "20"
    assert report["setup_gross_usd"] == "50"
    assert not report["monthly_within_limit"]
    assert not report["monthly_target_met"]


def test_forecast_refuses_missing_category_or_unpriced_item():
    scenario = _scenario()
    scenario["line_items"].pop(0)
    with pytest.raises(ValueError, match="Missing monthly cost categories"):
        forecast(scenario)
    scenario = _scenario()
    scenario["line_items"][0]["unit_price_usd"] = None
    with pytest.raises(ValueError, match="finite nonnegative"):
        forecast(scenario)


def test_forecast_refuses_duplicate_names_and_nonfinite_values():
    scenario = _scenario()
    scenario["line_items"][1]["name"] = scenario["line_items"][0]["name"]
    with pytest.raises(ValueError, match="unique name"):
        forecast(scenario)
    scenario = _scenario()
    scenario["line_items"][0]["quantity"] = "NaN"
    with pytest.raises(ValueError, match="finite nonnegative"):
        forecast(scenario)


@pytest.mark.parametrize("period", [[], {}, None, 1, "weekly"])
def test_forecast_cli_reports_invalid_period_without_traceback(
    period, tmp_path, monkeypatch, capsys
):
    scenario = _scenario()
    scenario["line_items"][0]["period"] = period
    path = tmp_path / "forecast.json"
    path.write_text(json.dumps(scenario), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["cost_forecast.py", str(path)])

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        "Forecast incomplete: Line item 1 needs a setup, monthly, or tooling period\n"
    )
