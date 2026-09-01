from __future__ import annotations

import numpy as np
import pandas as pd

from experiments import executable_surface_alpha as module


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp_ns": np.arange(100, dtype=np.int64) * 5_000_000_000,
            "trading_date": "2026-08-19",
            "near_bid": 99.0,
            "near_ask": 101.0,
            "far_bid": 79.0,
            "far_ask": 81.0,
            "near_strike": 25_000.0,
            "far_strike": 25_000.0,
            "signal": 0.0,
        }
    )


def test_near_straddle_uses_crossing_quotes() -> None:
    frame = _frame()
    frame.loc[7, ["near_bid", "near_ask"]] = [109.0, 111.0]
    assert module._pnl_points(frame, 1, 7, "near", 1) == 8.0
    assert module._pnl_points(frame, 1, 7, "near", -1) == -12.0


def test_calendar_uses_all_four_crossing_spreads() -> None:
    frame = _frame()
    frame.loc[7, ["near_bid", "near_ask", "far_bid", "far_ask"]] = [109, 111, 84, 86]
    assert module._pnl_points(frame, 1, 7, "calendar", 1) == 1.0
    assert module._pnl_points(frame, 1, 7, "calendar", -1) == -9.0


def test_trade_enters_next_state_and_requires_fixed_strike() -> None:
    frame = _frame()
    frame.loc[10, "signal"] = 2.0
    frame.loc[17, ["near_bid", "near_ask"]] = [109.0, 111.0]
    candidate = module.Candidate("x", "near", "signal", 1, 30)
    trades = module.trades_for(frame, candidate, 1.0)
    assert len(trades) == 1
    assert trades.iloc[0]["entry_timestamp_ns"] == frame.loc[11, "timestamp_ns"]
    assert trades.iloc[0]["pnl_points"] == 8.0
    frame.loc[17, "near_strike"] = 25_050.0
    assert module.trades_for(frame, candidate, 1.0).empty
