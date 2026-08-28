from __future__ import annotations

import numpy as np
import pandas as pd

from shaurya.research.intraday_volatility import (
    SeasonalMeanRegressor,
    _add_session_features,
    _forward_sum,
    calculate_metric,
    daily_block_bootstrap_skill,
)


def test_forward_sum_excludes_current_observation() -> None:
    values = np.array([1.0, 4.0, 9.0, 16.0])
    actual = _forward_sum(values, 2)
    np.testing.assert_allclose(actual[:2], [13.0, 25.0])
    assert np.isnan(actual[2:]).all()


def test_session_targets_are_strictly_forward() -> None:
    close = np.array([100.0, 101.0, 103.0, 102.0])
    frame = pd.DataFrame(
        {
            "minute": [555, 556, 557, 558],
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
        }
    )
    result = _add_session_features(frame, horizons=[2])
    expected_move = abs(np.log(103.0 / 100.0)) * 10_000.0
    np.testing.assert_allclose(result.loc[0, "abs_move_2"], expected_move)
    expected_rv = np.sqrt(np.log(101 / 100) ** 2 + np.log(103 / 101) ** 2) * 10_000.0
    np.testing.assert_allclose(result.loc[0, "realized_vol_2"], expected_rv)
    assert result["abs_move_2"].iloc[-2:].isna().all()


def test_seasonal_mean_uses_training_rows_only() -> None:
    train = pd.DataFrame({"minute": [560, 560, 565], "target": [1.0, 3.0, 9.0]})
    evaluation = pd.DataFrame({"minute": [560, 565, 570], "target": [100.0, 100.0, 100.0]})
    model = SeasonalMeanRegressor().fit(train, "target")
    np.testing.assert_allclose(model.predict(evaluation), [2.0, 9.0, 13.0 / 3.0])


def test_metric_and_daily_bootstrap_detect_better_model() -> None:
    actual = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    prediction = actual + 0.1
    seasonal = np.full_like(actual, 3.5)
    dates = pd.Series(pd.to_datetime(["2025-01-01"] * 3 + ["2025-01-02"] * 3))
    metric = calculate_metric(actual, prediction, seasonal, dates)
    interval = daily_block_bootstrap_skill(
        actual, prediction, seasonal, dates, samples=100, seed=7
    )
    assert metric.mae_skill_vs_seasonal > 0.9
    assert interval.lower_95 > 0.0
