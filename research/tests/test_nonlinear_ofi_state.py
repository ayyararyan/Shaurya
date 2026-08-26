from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
from shaurya.contracts.timing import IST

from shaurya.signals.fixed_target_panel import competitor_features
from shaurya.signals.nonlinear_ofi_state import (
    GEOMETRY_NAMES,
    HORIZONS_SECONDS,
    SAMPLING_SECONDS,
    _fit_logistic,
    _probability,
    _rolling_prediction,
    cadence_observations,
    metric_bundle,
    prepare_panel,
    split_masks,
)
from shaurya.signals.ofi_horserace import HorseRaceObservation


def _observation(second: int) -> HorseRaceObservation:
    features: dict[str, float] = {}
    for sampling in SAMPLING_SECONDS:
        for index, name in enumerate(competitor_features("C8", sampling, 10)):
            features[name] = 1.0 + second / 100.0 + sampling + index / 10.0
    start = datetime(2026, 8, 21, 9, 30, tzinfo=IST)
    stamp = int((start + timedelta(seconds=second)).timestamp() * 1e9)
    return HorseRaceObservation(
        tape_index=0,
        run_id="d50-test",
        receive_ts_ns=stamp,
        features=features,
        future_ticks={horizon: second / 100.0 for horizon in HORIZONS_SECONDS},
        past_ticks={},
        same_window_ticks={},
        window_start_ts_ns={},
    )


def test_five_second_cadence_keeps_last_observation_in_each_bucket() -> None:
    selected = cadence_observations([_observation(0), _observation(1), _observation(5)])
    assert len(selected) == 2
    assert selected[0].receive_ts_ns == _observation(1).receive_ts_ns


def test_panel_uses_exact_existing_c8_geometry_and_declared_splits() -> None:
    panel = prepare_panel([_observation(second) for second in range(0, 21_601, 5)])
    masks = split_masks(panel.timestamps)
    assert panel.geometry.shape == (len(panel.timestamps), len(GEOMETRY_NAMES))
    assert np.isfinite(panel.geometry).all()
    for column in (1, 2, 3, 4):
        assert np.all((panel.geometry[:, column] >= 0.0) & (panel.geometry[:, column] <= 1.0))
    assert all(mask.any() for mask in masks.values())


def test_rolling_fit_excludes_targets_that_have_not_matured() -> None:
    timestamps = np.arange(40, dtype=np.int64) * 5_000_000_000
    design = np.column_stack((np.arange(40, dtype=float), np.ones(40)))
    target = np.arange(40, dtype=float)
    first = _rolling_prediction(
        design,
        target,
        timestamps,
        position=39,
        window=200.0,
        horizon=30.0,
        alpha=1.0,
    )
    target[38] = 1_000_000.0
    second = _rolling_prediction(
        design,
        target,
        timestamps,
        position=39,
        window=200.0,
        horizon=30.0,
        alpha=1.0,
    )
    assert first == second


def test_logistic_gate_and_dynamic_baseline_metric_are_well_defined() -> None:
    design = np.column_stack((np.ones(20), np.linspace(-2, 2, 20)))
    target = (design[:, 1] > 0).astype(float)
    probability = _probability(design, _fit_logistic(design, target, 0.1))
    assert probability[:5].mean() < probability[-5:].mean()

    metric = metric_bundle(
        np.asarray([1.0, -1.0]),
        np.asarray([0.8, -0.8]),
        np.asarray([0.0, 0.0]),
    )
    assert metric["oos_r2_vs_m0"] == 0.96
