from __future__ import annotations

import numpy as np

from experiments import delta_hedged_volatility_carry as module


def test_implied_straddle_vol_round_trip() -> None:
    forward = 25_000.0
    strike = 25_000.0
    years = 7.0 / 365.25
    sigma = 0.14
    price = module.black_straddle(forward, strike, years, sigma)
    recovered = module.implied_straddle_vol(price, forward, strike, years)
    assert np.isclose(recovered, sigma, atol=1e-8)


def test_futures_cashflow_crosses_adverse_touch() -> None:
    assert module.futures_trade_cashflow(0.5, 99.0, 101.0) == -50.5
    assert module.futures_trade_cashflow(-0.5, 99.0, 101.0) == 49.5


def test_signal_compares_forecast_to_executable_iv() -> None:
    assert module._trade_signal(0.20, 0.14, 0.15, 0.02) == 1
    assert module._trade_signal(0.10, 0.14, 0.15, 0.02) == -1
    assert module._trade_signal(0.145, 0.14, 0.15, 0.02) == 0
