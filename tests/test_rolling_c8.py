from __future__ import annotations

from shaurya.analytics.rolling_c8 import (
    RollingC8Tracker,
    ScoreAccumulator,
    causal_training_positions,
    fit_forecast_cell,
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
