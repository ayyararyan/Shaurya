from __future__ import annotations

import math
from datetime import date

import pytest

from shaurya.analytics.variance_carry import (
    NSGVC_LOG_IV_INT_COEF,
    NSGVC_LOG_PRED_INTERCEPT,
    NSGVC_LOG_T_COEF,
    NSGVC_Q_THRESHOLD,
    NSGVC_RR400_THRESHOLD,
    forecast_integrated_realized_variance,
    nearest_strike,
    realized_volatility_forecast,
    variance_carry_state_from_slice,
)
from shaurya.surfaces.essvi import ESSVISlice


def _slice(*, support: float = 0.05) -> ESSVISlice:
    maturity = 7.0 / 365.25
    atm_iv = 0.0984
    return ESSVISlice(
        expiry=date(2026, 9, 15),
        maturity_years=maturity,
        forward=23_552.85,
        theta=(atm_iv**2) * maturity,
        rho=-0.25,
        psi=0.01,
        min_log_moneyness=-support,
        max_log_moneyness=support,
        quote_count=20,
    )


def test_frozen_q_mapping_is_exactly_reused() -> None:
    fitted = _slice()
    expected_prediction = math.exp(
        NSGVC_LOG_PRED_INTERCEPT
        + NSGVC_LOG_IV_INT_COEF * math.log(fitted.theta)
        + NSGVC_LOG_T_COEF * math.log(fitted.maturity_years)
    )
    prediction = forecast_integrated_realized_variance(
        implied_integrated_variance=fitted.theta,
        maturity_years=fitted.maturity_years,
    )
    assert prediction == pytest.approx(expected_prediction)

    state = variance_carry_state_from_slice(fitted)
    assert state.q_ratio == pytest.approx(expected_prediction / fitted.theta)
    assert state.rv_iv_vol_ratio == pytest.approx(math.sqrt(state.q_ratio))
    assert state.q_reference_threshold == NSGVC_Q_THRESHOLD
    assert state.q_below_reference is (state.q_ratio <= NSGVC_Q_THRESHOLD)


def test_rv_forecast_annualizes_integrated_variance_and_matches_q_identity() -> None:
    fitted = _slice()
    atm_iv = math.sqrt(fitted.theta / fitted.maturity_years)
    forecast = realized_volatility_forecast(
        atm_iv=atm_iv,
        maturity_years=fitted.maturity_years,
    )
    assert forecast.implied_integrated_variance == pytest.approx(fitted.theta)
    assert forecast.forecast_annualized_realized_variance == pytest.approx(
        forecast.forecast_integrated_realized_variance / fitted.maturity_years
    )
    assert forecast.forecast_annualized_realized_volatility == pytest.approx(
        math.sqrt(forecast.forecast_annualized_realized_variance)
    )
    assert forecast.forecast_annualized_realized_volatility == pytest.approx(
        atm_iv * math.sqrt(forecast.q_ratio)
    )


def test_rr400_uses_tradeable_50_point_atm_and_surface_wings() -> None:
    fitted = _slice()
    state = variance_carry_state_from_slice(fitted)

    assert nearest_strike(fitted.forward) == 23_550.0
    assert state.atm_strike == 23_550.0
    assert state.rr400 is not None
    assert state.put_400_iv is not None
    assert state.call_400_iv is not None
    assert state.rr400 == pytest.approx(state.put_400_iv - state.call_400_iv)
    assert state.rr400_reference_threshold == NSGVC_RR400_THRESHOLD
    assert state.rr400_below_reference is (
        state.rr400 <= NSGVC_RR400_THRESHOLD
    )


def test_rr400_refuses_surface_extrapolation() -> None:
    state = variance_carry_state_from_slice(_slice(support=0.01))
    assert state.rr400 is None
    assert state.rr400_below_reference is None
    assert state.rr400_reason == "strike_outside_fitted_support"
