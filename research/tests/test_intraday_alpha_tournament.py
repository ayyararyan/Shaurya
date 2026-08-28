from __future__ import annotations

import numpy as np
import pandas as pd

from shaurya.research.intraday_alpha_tournament import daily_pnl, strategy_metric


def test_turnover_cost_charges_entry_exit_and_flip() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01"] * 3),
            "forward_return_bps": [2.0, 3.0, -4.0],
        }
    )
    # Entry long (1), unchanged (0), flip to short (2), forced close (1): turnover = 4.
    result = daily_pnl(frame, np.array([1.0, 1.0, -1.0]), 6.0)
    assert result.loc[0, "turnover"] == 4.0
    assert result.loc[0, "pnl_bps"] == 9.0 - 12.0


def test_strategy_metric_uses_daily_returns() -> None:
    daily = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "pnl_bps": [1.0, 2.0, 3.0],
            "turnover": [2.0, 4.0, 6.0],
        }
    )
    metric = strategy_metric(daily)
    assert metric.days == 3
    assert metric.mean_daily_bps == 2.0
    assert metric.average_round_trips_per_day == 2.0
    assert metric.max_drawdown_bps == 0.0
