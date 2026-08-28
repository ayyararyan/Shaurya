from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from shaurya.research.regime_jump_alpha import (
    expiry_day_mask,
    fit_regime_calibration,
    jump_diagnostics,
    regime_jump_positions,
)


def _panel() -> pd.DataFrame:
    dates = pd.to_datetime(["2024-01-04", "2024-01-04", "2024-01-09", "2026-01-06", "2026-01-08"])
    return pd.DataFrame(
        {
            "date": dates,
            "elapsed": [30, 60, 30, 30, 60],
            "ret_1": [0.001, 0.001, 0.001, 0.20, -0.001],
            "ret_15": [0.01, -0.01, 0.02, 0.21, -0.02],
            "ret_60": [0.02, 0.03, 0.04, 0.30, 0.01],
            "rv_30": [0.010, 0.020, 0.030, 0.202, 0.015],
            "overnight_gap": [0.001, 0.001, -0.002, 0.05, -0.001],
            "forward_return_bps": [1.0, 2.0, 3.0, 9999.0, -9999.0],
        }
    )


def test_expiry_rule_switches_from_thursday_to_tuesday() -> None:
    dates = pd.Series(pd.to_datetime(["2025-08-28", "2025-09-02", "2026-01-08"]))
    assert expiry_day_mask(dates).tolist() == [True, True, False]


def test_calibration_does_not_observe_holdout_values() -> None:
    panel = _panel()
    first = fit_regime_calibration(panel, pd.Timestamp("2024-12-31"))
    panel.loc[panel["date"].dt.year == 2026, ["rv_30", "ret_60", "overnight_gap"]] = 1e9
    second = fit_regime_calibration(panel, pd.Timestamp("2024-12-31"))
    assert first == second


def test_positions_do_not_use_target_return() -> None:
    panel = _panel()
    first, calibration = regime_jump_positions(panel)
    panel["forward_return_bps"] *= -10_000
    second, _ = regime_jump_positions(panel, calibration)
    assert first.keys() == second.keys()
    for name in first:
        np.testing.assert_array_equal(first[name], second[name])


def test_jump_scale_excludes_latest_return() -> None:
    panel = _panel().iloc[[3]].copy()
    diagnostics = jump_diagnostics(panel, jump_z_threshold=4.0)
    assert bool(diagnostics["latest_jump"].iloc[0])
    assert diagnostics["continuous_return_15m"].iloc[0] == pytest.approx(0.01)


def test_candidate_positions_are_ternary_and_aligned() -> None:
    positions, _ = regime_jump_positions(_panel())
    assert len(positions) == 19
    for position in positions.values():
        assert len(position) == 5
        assert set(np.unique(position)).issubset({-1.0, 0.0, 1.0})


def test_missing_early_session_volatility_uses_fallback() -> None:
    panel = pd.concat([_panel(), _panel().assign(elapsed=5, rv_30=np.nan)], ignore_index=True)
    positions, calibration = regime_jump_positions(panel)
    assert 5 not in calibration.volatility_terciles
    assert all(len(position) == len(panel) for position in positions.values())
