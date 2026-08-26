"""Acceptance probes for D41 / EF-11/H1."""

from __future__ import annotations

from math import sin

import pytest

from shaurya.signals.ccz_ofi import normalised_level_feature
from shaurya.signals.mid_lag_ofi import (
    CONTEMPORANEOUS_WINDOWS_SECONDS,
    HORIZONS_SECONDS,
    LAG_SECONDS,
    OFI_WINDOWS_SECONDS,
    build_mid_lag_ofi_artifact,
    combined_feature_names,
    compact_result,
    hac_mean_test,
    holm_adjust,
    lag_feature_names,
    ofi_feature_names,
)
from shaurya.signals.ofi_horserace import HorseRaceObservation, HorseRaceTapeInput

SECOND = 1_000_000_000


def test_d41_val_03_combined_is_exact_lag_and_ofi_union() -> None:
    for window in OFI_WINDOWS_SECONDS:
        assert combined_feature_names(window) == (
            *lag_feature_names(),
            *ofi_feature_names(window),
        )


def test_d41_val_06_hac_and_holm_are_directional_and_deterministic() -> None:
    positive = hac_mean_test(
        [1.0 + 0.1 * sin(index) for index in range(200)],
        max_lag=30,
        alternative="greater",
    )
    assert positive["t_statistic"] > 0.0
    assert positive["p_value_raw"] < 0.05
    assert positive["hac_max_lag_rows"] == 30
    assert holm_adjust((0.01, 0.04, 0.03)) == pytest.approx((0.03, 0.06, 0.06))


def _observation(index: int) -> HorseRaceObservation:
    lag_values = {lag: sin(index / (7.0 + lag)) for lag in LAG_SECONDS}
    features: dict[str, float] = {}
    for window in CONTEMPORANEOUS_WINDOWS_SECONDS:
        for level in range(1, 11):
            features[normalised_level_feature(window, level, 10)] = (
                sin(index / (5.0 + window) + level / 11.0) / level
            )
    future = {
        horizon: 0.7 * lag_values[10.0]
        + 0.5 * features[normalised_level_feature(10.0, 1, 10)]
        + 0.01 * sin(index / 3.0 + horizon)
        for horizon in HORIZONS_SECONDS
    }
    same = {
        window: 0.9 * features[normalised_level_feature(window, 1, 10)]
        + 0.1 * sin(index / 9.0)
        for window in CONTEMPORANEOUS_WINDOWS_SECONDS
    }
    return HorseRaceObservation(
        tape_index=0,
        run_id="synthetic-d41",
        receive_ts_ns=index * SECOND,
        features=features,
        future_ticks=future,
        past_ticks=lag_values,
        same_window_ticks=same,
        window_start_ts_ns={
            window: int((index - window) * SECOND) for window in OFI_WINDOWS_SECONDS
        },
        connection_epoch=1,
    )


def test_d41_val_01_02_04_complete_synthetic_panel_recovers_both_families() -> None:
    observations = tuple(_observation(index) for index in range(1, 1201))
    tape = HorseRaceTapeInput(
        tape_index=0,
        run_id="synthetic-d41",
        instrument_id="NSE:NSE_FNO:NIFTY:future:2026-08-25",
        tape_sha256="0" * 64,
        observations=observations,
        depth200_publications=len(observations),
        depth20_publications=len(observations),
        observed_seconds=1200.0,
        failures={},
    )
    artifact = build_mid_lag_ofi_artifact(tape)
    assert len(artifact["future_comparisons"]) == 35
    assert len(artifact["lag_models"]) == 7
    assert len(artifact["contemporaneous_check"]) == 6
    for row in artifact["future_comparisons"]:
        assert row["lag_bank"]["absolute_oos_r2"] > 0.0
        if row["ofi_window_seconds"] == 10.0:
            assert row["lag_plus_ofi"]["absolute_oos_r2"] > row["lag_bank"]["absolute_oos_r2"]
            assert row["lag_plus_ofi"]["absolute_oos_r2"] > row["ofi_alone"]["absolute_oos_r2"]
        assert row["lag_plus_ofi"]["features"] == [
            *row["lag_bank"]["features"],
            *row["ofi_alone"]["features"],
        ]
    assert len({row["test_row_hash"] for row in artifact["future_comparisons"]}) == len(
        HORIZONS_SECONDS
    )
    compact = compact_result(artifact)
    assert len(compact["future_comparisons"]) == 35
    assert len(compact["lag_models"]) == 7
