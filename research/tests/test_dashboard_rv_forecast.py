from __future__ import annotations

import math

import pytest

from shaurya.analytics.dashboard import _rv_forecast_from_atm_payload, render_html


def test_dashboard_rv_forecast_uses_front_atm_and_exact_maturity_basis() -> None:
    atm = {
        "front": {
            "expiry": "2026-09-15",
            "maturity_days": 7.0,
            "implied_volatility": 0.12,
        }
    }
    forecast = _rv_forecast_from_atm_payload(atm)
    assert forecast["status"] == "ok"
    assert forecast["maturity_years"] == pytest.approx(7.0 / 365.0)
    assert forecast["implied_integrated_variance"] == pytest.approx(
        0.12**2 * (7.0 / 365.0)
    )
    assert forecast["forecast_annualized_realized_volatility"] == pytest.approx(
        0.12 * math.sqrt(float(forecast["q_ratio"]))
    )


def test_dashboard_html_contains_live_rv_forecast_band() -> None:
    html = render_html({"title": "test", "rv_forecast": {"status": "unavailable"}})
    assert 'id="rvForecastBand"' in html
    assert "FORECAST RV" in html
    assert "renderRvForecast" in html
