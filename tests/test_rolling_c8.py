from __future__ import annotations

import json
from pathlib import Path

from shaurya.analytics.rolling_c8 import (
    RollingC8Tracker,
    ScoreAccumulator,
    causal_training_positions,
    cell_key,
    fit_forecast_cell,
    fit_forecast_grid,
    forecast_win_score,
)
from shaurya.signals.fixed_target_panel import competitor_features
from shaurya.signals.ofi_horserace import HorseRaceObservation

SECOND = 1_000_000_000


def _observation(second: int, *, labelled: bool = True, epoch: int = 1) -> HorseRaceObservation:
    names = competitor_features("C8", 1.0, 10)
    signal = float((second % 11) - 5)
    features = {name: signal * (index + 1) / 100.0 for index, name in enumerate(names)}
    return HorseRaceObservation(
        tape_index=0,
        run_id="rolling-test",
        receive_ts_ns=second * SECOND,
        features=features,
        future_ticks=({5.0: 0.4 * signal + 0.1} if labelled else {}),
        past_ticks={},
        same_window_ticks={},
        window_start_ts_ns={1.0: second * SECOND - SECOND + 1},
        connection_epoch=epoch,
    )


def test_training_is_last_30_minutes_and_every_label_is_mature() -> None:
    observations = [_observation(second) for second in range(0, 2001, 5)]
    forecast = _observation(2000, labelled=False)
    observations[-1] = forecast

    positions = causal_training_positions(
        observations,
        forecast=forecast,
        lookback=1.0,
        horizon=5.0,
    )
    timestamps = [observations[position].receive_ts_ns // SECOND for position in positions]

    assert min(timestamps) == 200
    assert max(timestamps) == 1995 - 5  # 0.5 s gap + 5 s response must mature before t
    assert 0 not in timestamps
    assert 1995 not in timestamps


def test_forecast_fits_c8_without_requiring_the_forecast_target() -> None:
    observations = [_observation(second) for second in range(1000, 2001, 5)]
    observations[-1] = _observation(2000, labelled=False)

    result = fit_forecast_cell(
        observations,
        forecast_position=len(observations) - 1,
        lookback=1.0,
        horizon=5.0,
    )

    assert result["status"] == "forecast"
    assert result["train_n"] >= 20
    assert isinstance(result["prediction_ticks"], float)


def test_batched_multi_window_fit_matches_original_cell_estimator() -> None:
    observations = [_observation(second) for second in range(1000, 2001, 5)]
    observations[-1] = _observation(2000, labelled=False)
    position = len(observations) - 1

    original = fit_forecast_cell(
        observations,
        forecast_position=position,
        lookback=1.0,
        horizon=5.0,
        training_window_seconds=1800.0,
    )
    batched = fit_forecast_grid(observations, forecast_position=position)[(1800.0, 1.0, 5.0)]

    assert batched["prediction_ticks"] == original["prediction_ticks"]
    assert batched["baseline_ticks"] == original["baseline_ticks"]
    assert batched["selected_ridge_alpha"] == original["selected_ridge_alpha"]
    assert batched["train_n"] == original["train_n"]


def test_cumulative_r2_uses_each_forecasts_rolling_training_mean() -> None:
    score = ScoreAccumulator()
    score.score(actual=2.0, prediction=1.5, baseline=0.0)
    score.score(actual=-1.0, prediction=-0.5, baseline=0.5)

    payload = score.payload()

    expected = 1.0 - (0.5**2 + (-0.5) ** 2) / ((2.0 - 0.0) ** 2 + (-1.0 - 0.5) ** 2)
    assert payload["cumulative_oos_r2"] == expected
    assert payload["cumulative_direction_accuracy"] == 1.0
    assert payload["scored_n"] == 2


def test_fresh_tracker_does_not_backfill_historical_forecasts() -> None:
    tracker = RollingC8Tracker.fresh()

    assert tracker.last_forecast_anchor_ts_ns is None
    assert tracker.pending == []
    assert all(cell["scored_n"] == 0 for cell in tracker.payload(source={})["cells"])


def test_legacy_single_grid_state_migrates_only_to_thirty_minutes(tmp_path: Path) -> None:
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            {
                "started_at": "2026-08-21T08:31:34+00:00",
                "accumulators": {"1|5": {"forecasts_issued": 7, "scored_n": 6}},
                "pending": [],
                "latest_fit": {"1|5": {"status": "forecast", "train_n": 7000}},
                "recent_win_scores": [],
                "last_forecast_anchor_ts_ns": 100,
            }
        ),
        encoding="utf-8",
    )

    tracker = RollingC8Tracker.load(path)

    assert tracker.accumulators[cell_key(1.0, 5.0, 1800.0)].forecasts_issued == 7
    assert cell_key(1.0, 5.0, 120.0) not in tracker.accumulators
    cells = tracker.payload(source={})["cells"]
    thirty = next(cell for cell in cells if cell["cell_key"] == cell_key(1.0, 5.0, 1800.0))
    two = next(cell for cell in cells if cell["cell_key"] == cell_key(1.0, 5.0, 120.0))
    assert thirty["forecasts_issued"] == 7
    assert two["forecasts_issued"] == 0


def test_forecast_win_score_uses_forecast_magnitude_in_both_directions() -> None:
    assert forecast_win_score(prediction=2.0, actual=2.0) == 1
    assert forecast_win_score(prediction=2.0, actual=3.0) == 1
    assert forecast_win_score(prediction=2.0, actual=-2.0) == -1
    assert forecast_win_score(prediction=2.0, actual=1.5) == 0
    assert forecast_win_score(prediction=-2.0, actual=-3.0) == 1
    assert forecast_win_score(prediction=-2.0, actual=2.0) == -1
    assert forecast_win_score(prediction=0.0, actual=10.0) == 0


def test_rolling_win_score_keeps_only_latest_five_minutes() -> None:
    tracker = RollingC8Tracker.fresh()
    tracker.restore_recent_win_scores(
        [
            {
                "cell_key": cell_key(1.0, 5.0),
                "forecast_anchor_ts_ns": 1 * SECOND,
                "response_end_ts_ns": 100 * SECOND,
                "prediction_ticks": 2.0,
                "actual_ticks": 2.0,
            },
            {
                "cell_key": cell_key(1.0, 5.0),
                "forecast_anchor_ts_ns": 2 * SECOND,
                "response_end_ts_ns": 401 * SECOND,
                "prediction_ticks": 2.0,
                "actual_ticks": -3.0,
            },
            {
                "cell_key": cell_key(1.0, 5.0),
                "forecast_anchor_ts_ns": 3 * SECOND,
                "response_end_ts_ns": 500 * SECOND,
                "prediction_ticks": 2.0,
                "actual_ticks": 1.0,
            },
        ],
        as_of_ts_ns=500 * SECOND,
    )

    score = tracker.rolling_win_score(cell_key(1.0, 5.0))

    assert score == {
        "rolling_mean_win_score_5m": -0.5,
        "rolling_win_score_n_5m": 2,
        "rolling_wins_5m": 0,
        "rolling_neutral_5m": 1,
        "rolling_losses_5m": 1,
    }
