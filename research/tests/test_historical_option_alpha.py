from __future__ import annotations

import numpy as np
import pandas as pd

from shaurya.research.historical_option_alpha import SIGNALS, _offset, rolling_positions


def _panel() -> pd.DataFrame:
    rows = []
    for date in pd.bdate_range("2021-01-04", "2022-03-31"):
        for _minute in (0, 1):
            value = float(len(rows) + 1)
            rows.append(
                {
                    "date": date,
                    **{
                        column: value * (index + 1) for index, column in enumerate(SIGNALS.values())
                    },
                }
            )
    return pd.DataFrame(rows)


def test_offset_parses_atm_labels() -> None:
    assert _offset("ATM") == 0
    assert _offset("ATM-2") == -2
    assert _offset("ATM+2") == 2


def test_rolling_positions_are_symmetric_and_bounded() -> None:
    panel = _panel()
    positions, calibrations = rolling_positions(panel)
    assert calibrations
    for signal in SIGNALS:
        positive = positions[f"positive_{signal}"]
        negative = positions[f"negative_{signal}"]
        np.testing.assert_array_equal(positive, -negative)
        assert set(np.unique(positive)) <= {-1.0, 0.0, 1.0}


def test_future_changes_do_not_change_prior_month_calibration() -> None:
    panel = _panel()
    baseline, baseline_calibration = rolling_positions(panel)
    changed = panel.copy()
    changed.loc[changed["date"] >= pd.Timestamp("2022-03-01"), list(SIGNALS.values())] *= 1e9
    replay, replay_calibration = rolling_positions(changed)
    assert baseline_calibration == replay_calibration
    prior = (panel["date"] < pd.Timestamp("2022-03-01")).to_numpy()
    for name in baseline:
        np.testing.assert_array_equal(baseline[name][prior], replay[name][prior])
