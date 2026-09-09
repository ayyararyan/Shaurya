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
    assert forecast["implied_integrated_variance"] == pytest.approx(0.12**2 * (7.0 / 365.0))
    assert forecast["forecast_annualized_realized_volatility"] == pytest.approx(
        0.12 * math.sqrt(float(forecast["q_ratio"]))
    )


def test_dashboard_html_contains_live_rv_forecast_band() -> None:
    html = render_html({"title": "test", "rv_forecast": {"status": "unavailable"}})
    assert 'id="rvForecastBand"' in html
    assert "FORECAST RV" in html
    assert "renderRvForecast" in html


@pytest.mark.parametrize("value", [None, 0.0, -0.1, float("nan"), float("inf")])
def test_invalid_atm_has_no_numeric_forecast(value: float | None) -> None:
    forecast = _rv_forecast_from_atm_payload(
        {"front": {"implied_volatility": value, "maturity_days": 7.0}}
    )
    assert forecast["status"] == "unavailable"
    assert "forecast_annualized_realized_volatility" not in forecast


def test_live_and_history_forecasts_use_their_own_surface_frame() -> None:
    from datetime import timedelta

    from test_anl03_dashboard import VALUATION, _chain, _engine

    from shaurya.analytics.dashboard import build_history_payload, build_payload

    engine = _engine()
    assert (
        build_payload(engine, title="test", source="fixture")["rv_forecast"]["status"]
        == "unavailable"
    )
    for row in _chain():
        engine.ingest(row)
    engine.fit(VALUATION)
    first = build_payload(engine, title="test", source="fixture")
    engine.fit(VALUATION + timedelta(seconds=6))
    current = build_payload(engine, title="test", source="fixture")
    historical = build_history_payload(engine, 0)
    assert historical["rv_forecast"] == first["rv_forecast"]
    assert current["rv_forecast"]["maturity_years"] != historical["rv_forecast"]["maturity_years"]
    for payload in (first, current, historical):
        forecast = payload["rv_forecast"]
        front = payload["atm"]["front"]
        t = front["maturity_days"] / 365.0
        iv_int = front["implied_volatility"] ** 2 * t
        expected = math.exp(
            -0.8941884292 + 0.9083950192 * math.log(iv_int) + 0.0481227276 * math.log(t)
        )
        assert forecast["forecast_annualized_realized_volatility"] == pytest.approx(
            math.sqrt(expected / t)
        )
        assert forecast["expiry"] == front["expiry"]


def test_failed_fit_has_no_rv_forecast() -> None:
    from test_anl03_dashboard import VALUATION, _engine

    from shaurya.analytics.dashboard import build_payload

    engine = _engine()
    engine.fit(VALUATION)
    assert (
        build_payload(engine, title="test", source="fixture")["rv_forecast"]["status"]
        == "unavailable"
    )
