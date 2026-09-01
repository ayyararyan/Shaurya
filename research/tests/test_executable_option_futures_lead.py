from __future__ import annotations

import numpy as np
import pandas as pd

from experiments import executable_option_futures_lead as module


def test_crossing_pnl_and_one_second_delay() -> None:
    index = pd.date_range("2026-01-06 09:16:00", periods=40, freq="1s")
    frame = pd.DataFrame(index=index)
    frame["implied_forward"] = 25_000.0
    frame.loc[index[10]:, "implied_forward"] = 25_010.0
    frame["future_mid"] = 25_000.0
    frame["future_bid"] = 24_999.0
    frame["future_ask"] = 25_001.0
    frame.loc[index[16], ["future_bid", "future_ask"]] = [25_009.0, 25_011.0]
    values = module.trade_returns(frame, "option_raw", 0.0001, 0.0)
    assert len(values) == 2
    assert np.isclose(values[0], 8.0 / 25_001.0 * 10_000.0)


def test_summary_cost_ladder() -> None:
    result = module.summary(np.asarray([2.0, 4.0]))
    assert result["gross_mean_bps"] == 3.0
    assert result["net_mean_bps_at_1"] == 2.0
