from __future__ import annotations

import math

import numpy as np
import pytest

from shaurya.research.option_surface_alpha import (
    SelectionGate,
    SurfaceQuote,
    _black76_price,
    conformal_positions,
    executable_straddle_pnl_bps,
    fit_surface_factors,
    holm_rejections,
    validate_candidate,
)


def _surface_quotes() -> list[SurfaceQuote]:
    forward = 25_000.0
    maturity = 7.0 / 365.25
    quotes = []
    for strike in range(24_700, 25_301, 50):
        log_money = math.log(strike / forward)
        volatility = 0.16 - 0.45 * log_money + 9.0 * log_money * log_money
        for is_call in (True, False):
            mid = _black76_price(
                forward=forward,
                strike=float(strike),
                maturity_years=maturity,
                volatility=volatility,
                risk_free_rate=0.06,
                is_call=is_call,
            )
            quotes.append(
                SurfaceQuote(
                    strike=float(strike),
                    is_call=is_call,
                    bid=max(mid - 0.25, 0.01),
                    ask=mid + 0.25,
                    depth_imbalance=log_money,
                )
            )
    return quotes


def test_surface_factors_recover_atm_and_skew() -> None:
    factors = fit_surface_factors(
        _surface_quotes(), forward=25_000.0, maturity_years=7.0 / 365.25
    )

    assert factors is not None
    assert factors.quote_count >= 10
    assert factors.atm_iv == pytest.approx(0.16, abs=0.004)
    assert factors.variance_skew < 0.0
    assert factors.fit_rmse_iv < 0.003
    assert factors.parity_residual_rms_to_forward < 1e-8


def test_surface_fit_refuses_insufficient_or_invalid_quotes() -> None:
    assert (
        fit_surface_factors(
            _surface_quotes()[:4], forward=25_000.0, maturity_years=7.0 / 365.25
        )
        is None
    )
    assert fit_surface_factors(_surface_quotes(), forward=0.0, maturity_years=0.1) is None


def test_validation_gate_does_not_need_final_target() -> None:
    target = np.linspace(-1.0, 1.0, 400)
    baseline = np.zeros_like(target)
    predictions = [target + offset for offset in (0.01, -0.01, 0.02, -0.02, 0.0)]

    result = validate_candidate(
        name="surface",
        discovery_target=target,
        discovery_prediction=target,
        discovery_baseline=baseline,
        validation_target=target,
        validation_predictions=predictions,
        validation_baseline=baseline,
        gate=SelectionGate(maximum_validation_p_value=0.05),
    )

    assert result.promoted
    assert result.seed_pass_rate == 1.0
    assert result.validation_p_value <= 0.05


def test_holm_stops_at_first_failed_ordered_hypothesis() -> None:
    assert holm_rejections({"a": 0.01, "b": 0.021, "c": 0.9}) == {"a", "b"}


def test_conformal_abstention_and_executable_costs() -> None:
    positions = conformal_positions(
        np.asarray([5.0, -5.0, 0.5]),
        np.ones(50),
        np.asarray([1.0, 1.0, 1.0]),
    )
    assert positions.tolist() == [1, -1, 0]

    pnl = executable_straddle_pnl_bps(
        positions,
        entry_bid_to_forward=np.asarray([0.0099, 0.0099, 0.0099]),
        entry_ask_to_forward=np.asarray([0.0101, 0.0101, 0.0101]),
        exit_bid_to_forward=np.asarray([0.0104, 0.0094, 0.0100]),
        exit_ask_to_forward=np.asarray([0.0106, 0.0096, 0.0102]),
    )
    assert pnl.tolist() == pytest.approx([3.0, 3.0, 0.0])
