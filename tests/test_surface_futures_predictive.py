from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from shaurya.data.depth_thinning_analysis import FULL, BookState
from shaurya.signals.surface_futures_predictive import (
    DECISION_GAP_SECONDS,
    EXPIRIES,
    FIT_INTERVAL_SECONDS,
    FUTURES_INSTRUMENT_ID,
    NANOSECONDS_PER_SECOND,
    QUALITY_NUMERIC_NAMES,
    RESPONSE_SECONDS,
    FrameDraft,
    FutureBookSeries,
    SurfacePredictiveObservation,
    _filtered_positions,
    build_ofi_prefix,
    build_predictive_observations,
    build_scan_artifact,
    chronological_split,
    essvi_atm_shape,
    essvi_implied_volatility,
    fit_preprocessor,
    horse_aligned_five_level_names,
    lagged_surface_source_positions,
    lob_features,
    model_raw_names,
    ofi_feature,
    select_alpha,
    surface_economic_features,
    surface_feature,
    term_feature,
    trailing_ofi_features,
)

SECOND = NANOSECONDS_PER_SECOND
BASE = int(datetime(2026, 8, 19, 6, 34, tzinfo=UTC).timestamp() * SECOND)


def _state(
    seconds: float,
    *,
    midpoint: float = 100.025,
    bid_quantities: tuple[int, ...] = (100, 110, 120, 130, 140),
    ask_quantities: tuple[int, ...] = (100, 110, 120, 130, 140),
    bid_orders: tuple[int, ...] = (5, 6, 7, 8, 9),
    ask_orders: tuple[int, ...] = (5, 6, 7, 8, 9),
    epoch: int = 1,
    flags: tuple[str, ...] = (),
) -> BookState:
    best_bid = midpoint - 0.025
    best_ask = midpoint + 0.025
    return BookState(
        channel=FULL,
        receive_ts_ns=BASE + int(round(seconds * SECOND)),
        receive_sequence=int(seconds * 2) + 1,
        connection_epoch=epoch,
        bids=tuple(
            (round(best_bid - 0.05 * level, 2), bid_quantities[level], bid_orders[level])
            for level in range(5)
        ),
        asks=tuple(
            (round(best_ask + 0.05 * level, 2), ask_quantities[level], ask_orders[level])
            for level in range(5)
        ),
        rows_in_burst=1,
        quality_flags=flags,
    )


def _surface_snapshot(
    stamp: datetime, *, theta_shift: float = 0.0, smoothing: str = "smoothed"
) -> Any:
    parameters = []
    support = []
    for index, expiry in enumerate(EXPIRIES):
        theta = 0.002 + index * 0.001 + theta_shift
        rho = -0.35 + index * 0.05
        psi = 0.04 + index * 0.01
        for name, value in (("theta", theta), ("rho", rho), ("psi", psi)):
            parameters.append(SimpleNamespace(name=f"{expiry.isoformat()}.{name}", value=value))
        support.append(
            {
                "expiry": expiry.isoformat(),
                "maturity_years": 0.02 + index * 0.03,
                "min_log_moneyness": -0.08,
                "max_log_moneyness": 0.08,
                "quote_count": 20 + index,
            }
        )
    return SimpleNamespace(
        frame=SimpleNamespace(parameters=parameters),
        diagnostics={
            "support": support,
            "weighted_r_squared": 0.9,
            "weighted_rmse_total_variance": 0.01,
            "temporal_smoothing": {
                "status": smoothing,
                "is_temporally_smoothed": smoothing == "smoothed",
            },
            "input": {"used_quote_count": 63},
        },
        fit_timestamp=stamp,
    )


def _observation(index: int) -> SurfacePredictiveObservation:
    signal = math.sin(index / 9.0)
    economic = {
        "surface__x": signal,
        "surface__x__delta_1f": math.cos(index / 11.0),
        "surface__x__velocity_per_second": math.cos(index / 11.0) / 5.0,
    }
    lob = {
        "lob__spread_ticks": 1.0,
        "lob__microprice_tilt_ticks": signal * 0.2,
        "lob__l1_total_quantity": 200.0,
        "lob__log1p_l1_total_quantity": math.log1p(200.0),
        "lob__quantity_imbalance_l1": signal * 0.1,
    }
    ofi = {
        ofi_feature(5.0, name): signal * multiplier
        for multiplier, name in enumerate(
            (
                "cks_l1_raw",
                "cks_l1_depth_adjusted",
                "pk_level1_raw",
                "pk_levels2_5_raw",
                "pk_level1_depth_adjusted",
                "pk_levels2_5_depth_adjusted",
            ),
            start=1,
        )
    }
    quality = dict.fromkeys(QUALITY_NUMERIC_NAMES)
    quality["quality__weighted_r_squared"] = 0.8 + 0.01 * signal
    quality["quality__surface_age_seconds"] = 100.0 if index % 2 else 300.0
    target = 0.7 * signal + 0.05 * math.sin(index / 3.0)
    return SurfacePredictiveObservation(
        sequence=index + 1,
        receive_ts_ns=BASE + index * 5 * SECOND,
        connection_epoch=1,
        economic=economic,
        quality_numeric=quality,
        quality_categorical={"quality__smoothing_status": "smoothed"},
        lob=lob,
        ofi=ofi,
        y_future_ticks=target,
        y_past_ticks=0.5 * signal,
        y_same_ticks=1.2 * signal,
        target_start_age_seconds=0.1,
        target_end_age_seconds=0.2,
        surface_age_seconds=float(quality["quality__surface_age_seconds"] or 0.0),
        smoothing_status="smoothed",
    )


def test_analytic_atm_skew_and_curvature_match_central_finite_difference() -> None:
    theta, rho, psi, maturity = 0.004, -0.42, 0.055, 0.08
    atm, skew, curvature = essvi_atm_shape(
        theta=theta, rho=rho, psi=psi, maturity_years=maturity
    )
    step = 1e-5
    left = essvi_implied_volatility(
        -step, theta=theta, rho=rho, psi=psi, maturity_years=maturity
    )
    centre = essvi_implied_volatility(
        0.0, theta=theta, rho=rho, psi=psi, maturity_years=maturity
    )
    right = essvi_implied_volatility(
        step, theta=theta, rho=rho, psi=psi, maturity_years=maturity
    )
    assert atm == pytest.approx(centre, rel=1e-12)
    assert skew == pytest.approx((right - left) / (2.0 * step), rel=2e-7)
    assert curvature == pytest.approx((right - 2.0 * centre + left) / step**2, rel=2e-4)


def test_surface_features_include_levels_velocities_and_adjacent_terms() -> None:
    first = _surface_snapshot(datetime(2026, 8, 19, 12, 0, tzinfo=UTC))
    economic, levels = surface_economic_features(first, None, None)
    assert economic is None and levels is not None
    second = _surface_snapshot(first.fit_timestamp + timedelta(seconds=5), theta_shift=0.0001)
    previous_ns = int(round(first.fit_timestamp.timestamp() * SECOND))
    economic, _ = surface_economic_features(second, levels, previous_ns)
    assert economic is not None
    theta_name = surface_feature(EXPIRIES[0], "theta")
    assert economic[f"{theta_name}__delta_1f"] == pytest.approx(0.0001)
    assert economic[f"{theta_name}__velocity_per_second"] == pytest.approx(0.00002)
    assert term_feature(EXPIRIES[0], EXPIRIES[1], "atm_skew") in economic
    assert all("forward" not in name for name in economic)


def test_target_asof_enforces_age_epoch_and_right_edge_without_lookahead() -> None:
    series = FutureBookSeries([_state(0.0), _state(1.0, midpoint=100.075), _state(7.0)])
    move = series.move(BASE, BASE + SECOND, connection_epoch=1)
    assert move is not None and move.value_ticks == pytest.approx(1.0)
    assert series.move(BASE, BASE + 8 * SECOND, connection_epoch=1) is None
    assert (
        series.move_failure_reason(BASE, BASE + 8 * SECOND, connection_epoch=1)
        == "right_edge_uncovered"
    )
    assert series.as_of(BASE + 6 * SECOND, connection_epoch=1) is not None
    assert series.as_of(BASE + 6 * SECOND + 1, connection_epoch=1) is not None
    assert series.as_of(BASE + 6 * SECOND, connection_epoch=2) is None
    one_state = FutureBookSeries([_state(0.0)])
    assert one_state.as_of(BASE + 6 * SECOND, connection_epoch=1) is not None
    assert one_state.as_of(BASE + 6 * SECOND + 1, connection_epoch=1) is None
    assert (
        one_state.as_of_failure_reason(BASE + 6 * SECOND + 1, connection_epoch=1)
        == "stale_state"
    )
    invalid = FutureBookSeries([_state(0.0, flags=("sequence_gap",))])
    assert invalid.as_of(BASE, connection_epoch=1) is None
    crossed = FutureBookSeries([_state(0.0, epoch=1), _state(10.0, epoch=2)])
    assert (
        crossed.move_failure_reason(BASE, BASE + 10 * SECOND, connection_epoch=1)
        == "epoch_right_edge"
    )


def test_five_level_lob_formulas_and_average_size_proxy_semantics() -> None:
    state = _state(
        0.0,
        bid_quantities=(120, 100, 90, 80, 70),
        ask_quantities=(80, 90, 100, 110, 120),
    )
    features = lob_features(state)
    assert features is not None
    assert features["lob__spread_ticks"] == pytest.approx(1.0)
    assert features["lob__l1_total_quantity"] == pytest.approx(200.0)
    assert features["lob__log1p_l1_total_quantity"] == pytest.approx(math.log1p(200.0))
    assert features["lob__quantity_imbalance_l1"] == pytest.approx(0.2)
    assert features["lob__quantity_imbalance_cum5"] == pytest.approx(-40 / 960)
    assert features["lob__bid_average_order_size_proxy_5"] == pytest.approx(460 / 35)
    assert "lob__bid_slope" in features and "lob__curvature_asymmetry_ask_minus_bid" in features


def test_horse_aligned_mapping_restores_exact_m0_m3b_and_labels_five_level_analogue() -> None:
    observations = [_observation(index) for index in range(200)]
    assert horse_aligned_five_level_names("H0", 5.0, observations) == (
        "lob__log1p_l1_total_quantity",
        "lob__spread_ticks",
    )
    assert horse_aligned_five_level_names("H3b", 1.0, observations) == (
        "lob__log1p_l1_total_quantity",
        "lob__spread_ticks",
        ofi_feature(1.0, "cks_l1_depth_adjusted"),
    )
    names = horse_aligned_five_level_names("H4_5L", 2.0, observations)
    assert names[-2:] == (
        ofi_feature(2.0, "pk_level1_raw"),
        ofi_feature(2.0, "pk_levels2_5_raw"),
    )
    with pytest.raises(ValueError, match="unknown horse-aligned"):
        horse_aligned_five_level_names("M4", 2.0, observations)


def test_missing_lob_denominators_are_missing_not_zero() -> None:
    state = _state(0.0, bid_orders=(0, 0, 0, 0, 0))
    assert lob_features(state) is None


def test_ofi_reuses_canonical_sign_and_price_keyed_marginal_bands() -> None:
    states = [_state(float(index)) for index in range(12)]
    states[-1] = _state(
        11.0,
        bid_quantities=(110, 120, 120, 130, 140),
        ask_quantities=(90, 105, 120, 130, 140),
    )
    series = FutureBookSeries(states)
    prefix = build_ofi_prefix(states)
    features = trailing_ofi_features(
        prefix, series, anchor_ts_ns=BASE + 11 * SECOND, connection_epoch=1
    )
    assert features is not None
    assert features[ofi_feature(5.0, "cks_l1_raw")] == pytest.approx(20.0)
    assert features[ofi_feature(5.0, "pk_level1_raw")] == pytest.approx(20.0)
    assert features[ofi_feature(5.0, "pk_levels2_5_raw")] == pytest.approx(15.0)
    assert features[ofi_feature(5.0, "cks_l1_depth_adjusted")] > 0.0
    assert all(
        ofi_feature(window, "cks_l1_raw") in features
        for window in (0.5, 1.0, 2.0, 5.0, 10.0)
    )


def test_exact_future_past_and_same_geometry_from_one_surface_anchor() -> None:
    states = [_state(index / 2.0, midpoint=100.025 + index * 0.05) for index in range(41)]
    draft = FrameDraft(
        sequence=1,
        receive_ts_ns=BASE + 10 * SECOND,
        connection_epoch=1,
        economic={"surface__x": 1.0},
        quality_numeric=dict.fromkeys(QUALITY_NUMERIC_NAMES),
        quality_categorical={"quality__smoothing_status": "smoothed"},
        surface_age_seconds=100.0,
        smoothing_status="smoothed",
    )
    observations, failures = build_predictive_observations([draft], states)
    assert failures == {
        "no_current_future_state": 0,
        "lob_unusable": 0,
        "ofi_incomplete": 0,
        "future_target_uncovered": 0,
        "past_mirror_uncovered": 0,
        "same_window_uncovered": 0,
    }
    assert len(observations) == 1
    assert observations[0].y_future_ticks == pytest.approx(10.0)
    assert observations[0].y_past_ticks == pytest.approx(10.0)
    assert observations[0].y_same_ticks == pytest.approx(10.0)


def test_optional_ten_second_ofi_window_does_not_collapse_primary_sample() -> None:
    states = [_state(index / 2.0, midpoint=100.025 + index * 0.05) for index in range(30)]
    draft = FrameDraft(
        sequence=1,
        receive_ts_ns=BASE + 7 * SECOND,
        connection_epoch=1,
        economic={"surface__x": 1.0},
        quality_numeric=dict.fromkeys(QUALITY_NUMERIC_NAMES),
        quality_categorical={"quality__smoothing_status": "smoothed"},
        surface_age_seconds=100.0,
        smoothing_status="smoothed",
    )
    observations, failures = build_predictive_observations([draft], states)
    assert len(observations) == 1
    assert ofi_feature(5.0, "cks_l1_raw") in observations[0].ofi
    assert ofi_feature(10.0, "cks_l1_raw") not in observations[0].ofi
    assert failures["ofi_robustness_w10_unavailable"] == 1


def test_chronological_split_has_120_second_embargo() -> None:
    observations = [_observation(index) for index in range(200)]
    split = chronological_split(observations)
    assert len(split.train) == 140
    assert split.embargo_end_ts_ns - split.boundary_ts_ns == 120 * SECOND
    assert all(
        observations[position].receive_ts_ns > split.embargo_end_ts_ns
        for position in split.test
    )


def test_train_only_quality_vocabulary_and_model_block_isolation() -> None:
    from dataclasses import replace

    observations = [_observation(index) for index in range(80)]
    observations[70] = replace(
        observations[70],
        quality_categorical={"quality__smoothing_status": "raw_unsmoothed:new_reason"},
    )
    training = tuple(range(60))
    sq_names = model_raw_names("SQ", observations)
    processor = fit_preprocessor(observations, training, raw_names=sq_names)
    transformed = processor.transform(observations, (70,))
    other = transformed.names.index("quality__smoothing_status__other")
    assert transformed.matrix[0, other] == 1.0
    assert len(processor.transform(observations, training).matrix) == 60
    s_processor = fit_preprocessor(
        observations, training, raw_names=model_raw_names("S", observations)
    )
    assert all("quality__" not in name for name in s_processor.transformed_names)


def test_alpha_selection_is_unchanged_when_outside_training_targets_change() -> None:
    from dataclasses import replace

    observations = [_observation(index) for index in range(260)]
    training = tuple(range(180))
    names = model_raw_names("LOS", observations)
    first = select_alpha(observations, training, raw_names=names, source="future")
    changed = observations.copy()
    for index in range(180, len(changed)):
        changed[index] = replace(changed[index], y_future_ticks=1_000_000.0)
    second = select_alpha(changed, training, raw_names=names, source="future")
    assert first == second


def test_freshness_filter_preserves_primary_split_positions() -> None:
    observations = [_observation(index) for index in range(100)]
    positions = tuple(range(100))
    fresh = _filtered_positions(observations, positions, maximum_surface_age_seconds=240.0)
    assert fresh == tuple(index for index in positions if index % 2 == 1)


def test_lag_placebo_uses_same_epoch_past_without_wrap() -> None:
    observations = [_observation(index) for index in range(100)]
    mapping = lagged_surface_source_positions(observations)
    assert mapping
    assert min(mapping) == 60
    for position, source in mapping.items():
        assert source < position
        assert observations[position].connection_epoch == observations[source].connection_epoch
        assert (
            observations[position].receive_ts_ns - observations[source].receive_ts_ns
            >= 300 * SECOND
        )


def test_complete_artifact_is_deterministic_and_keeps_quality_increment_separate() -> None:
    observations = [_observation(index) for index in range(320)]
    split = chronological_split(observations)
    metadata = {"sha256": "fixture", "book_channel": "Full five-level"}
    replay = {"attempted_fits": 320, "join_failures": {}}
    first = build_scan_artifact(
        observations,
        split,
        source_metadata=metadata,
        replay_metadata=replay,
        replicates=3,
        seed=7,
        code_commit="fixture",
    )
    second = build_scan_artifact(
        observations,
        split,
        source_metadata=metadata,
        replay_metadata=replay,
        replicates=3,
        seed=7,
        code_commit="fixture",
    )
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert "LOS_minus_LO_oos_r2" in first["headline"]
    assert "LOSQ_minus_LOS_oos_r2" in first["headline"]
    assert {row["source"] for row in first["model_scores"]} == {"future", "past", "same"}
    assert len(first["model_scores"]) == 24
    assert len(first["correlations"]) == 36
    assert all(
        row["hac_lag_frames"] == 2 and "bh_fdr_q_value" in row
        for row in first["correlations"]
    )
    held_out_future = [
        row
        for row in first["correlations"]
        if row["source"] == "future" and row["scope"] == "held_out"
    ]
    assert held_out_future
    assert all(
        "S_standardized_ridge_coefficient" in row
        and "LOS_mean_absolute_held_out_contribution_ticks" in row
        for row in held_out_future
    )
    assert {row["scope"] for row in first["surface_collinearity"]} == {
        "full",
        "training",
        "held_out",
    }
    assert all("strongest_25_pairs" in row for row in first["surface_collinearity"])
    paired = {
        (row["source"], row["base_model"], row["enhanced_model"])
        for row in first["paired_inference"]
    }
    expected_pairs = {
        ("S", "L"),
        ("S", "O"),
        ("S", "LO"),
        ("LO", "LOS"),
        ("S", "SQ"),
        ("LOS", "LOSQ"),
    }
    assert paired == {
        (source, base, enhanced)
        for source in ("future", "past", "same")
        for base, enhanced in expected_pairs
    }
    assert all(
        row["newey_west_lag_frames"] == 2
        and row["stationary_bootstrap_mean_block_frames"] == 6.0
        and row["non_overlapping_block_seconds"] == 10.0
        for row in first["paired_inference"]
    )
    assert any(row.get("arm") == "surface_lag_300s_no_wrap" for row in first["lag_placebo"])


def test_scan_identity_and_target_instrument_are_frozen() -> None:
    assert FUTURES_INSTRUMENT_ID == "NSE:NSE_FNO:NIFTY:future:2026-08-25"
    assert FIT_INTERVAL_SECONDS == 5.0
    assert DECISION_GAP_SECONDS == 0.5
    assert RESPONSE_SECONDS == 5.0
