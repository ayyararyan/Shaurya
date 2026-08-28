from __future__ import annotations

import numpy as np
import pandas as pd

from shaurya.research.rolling_gap_validation import _centered_rank, rolling_gap_positions


def test_centered_rank_uses_only_frozen_reference() -> None:
    reference = np.asarray([1.0, 2.0, 3.0])
    first = _centered_rank(pd.Series([0.0, 2.0, 4.0]), reference)
    second = _centered_rank(pd.Series([0.0, 2.0, 4.0, 1e9]), reference)[:3]
    np.testing.assert_array_equal(first, second)


def test_month_calibration_does_not_observe_test_month() -> None:
    dates = pd.date_range("2021-01-01", periods=130, freq="B")
    rows = []
    for index, date in enumerate(dates):
        rows.append(
            {
                "date": date,
                "elapsed": 30,
                "overnight_gap": 0.001 + index * 1e-6,
                "rv_30": 0.01 + index * 1e-5,
            }
        )
    panel = pd.DataFrame(rows)
    start = panel["date"].dt.to_period("M").iloc[-1]
    first, calibrations = rolling_gap_positions(panel, start_month=start, training_sessions=120)
    panel.loc[panel["date"].dt.to_period("M") == start, ["overnight_gap", "rv_30"]] = 1e9
    second, changed_calibrations = rolling_gap_positions(
        panel, start_month=start, training_sessions=120
    )
    assert calibrations == changed_calibrations
    assert first.keys() == second.keys()
