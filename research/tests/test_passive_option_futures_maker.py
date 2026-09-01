from __future__ import annotations

import numpy as np
import pandas as pd

from experiments import passive_option_futures_maker as module


def _frame() -> pd.DataFrame:
    index = pd.date_range("2026-01-06 09:16:00", periods=80, freq="1s")
    frame = pd.DataFrame(index=index)
    frame["implied_forward"] = 25_000.0
    frame.loc[index[10]:, "implied_forward"] = 25_010.0
    frame["future_mid"] = 25_000.0
    frame["future_bid"] = 24_999.0
    frame["future_ask"] = 25_001.0
    return frame


def test_requires_strict_quote_through_and_exits_by_crossing() -> None:
    frame = _frame()
    candidate = module.Candidate(ttl_seconds=2, hold_seconds=5)
    # Placement is index 11 at bid 24999. Touching 24999 is not a strict fill.
    frame.loc[frame.index[12], "future_ask"] = 24_999.0
    fills, orders = module.simulate_session(frame, candidate, 0.0001, 0.0)
    assert orders > 0
    assert fills.empty
    # Strictly through at index 12 fills at the original 24999 bid.
    frame.loc[frame.index[12], "future_ask"] = 24_998.0
    frame.loc[frame.index[17], "future_bid"] = 25_009.0
    fills, _ = module.simulate_session(frame, candidate, 0.0001, 0.0)
    assert len(fills) == 1
    assert np.isclose(fills.iloc[0]["gross_pnl_bps"], 10.0 / 24_999.0 * 10_000.0)


def test_summary_charges_only_filled_orders() -> None:
    fills = pd.DataFrame({"gross_pnl_bps": [1.0, 2.0], "fill_wait_seconds": [1, 2]})
    result = module.summarize(fills, orders=10)
    assert result["fill_rate"] == 0.2
    assert result["net_total_bps_at_0.5"] == 2.0
    assert result["net_bps_per_order_at_0.5"] == 0.2
