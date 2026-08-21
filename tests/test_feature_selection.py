from __future__ import annotations

import math

import pytest

from shaurya.data.depth_thinning_analysis import BookState
from shaurya.signals.ccz_ofi import average_feature
from shaurya.signals.feature_selection import (
    CAUSAL_GAP_SECONDS,
    EVIDENCE_LABEL,
    INTERACTION_FEATURE_NAMES,
    OFI_DEPTHS,
    OFI_WINDOWS_SECONDS,
    PRICE_LAG_SECONDS,
    REGISTRY_VERSION,
    SURFACE_EW_ALPHA,
    TARGET_HORIZON_SECONDS,
    FeatureConstructionResult,
    FeatureQualityGateConfig,
    SurfaceQualityGate,
    apply_feature_quality_gates,
    build_feature_selection_rows,
    build_registry,
    price_lag_feature,
    surface_innovation_feature,
)
from shaurya.signals.ofi_horserace import HorseRaceObservation
from shaurya.signals.surface_futures_predictive import (
    EXPIRIES,
    FrameDraft,
    surface_feature,
)

NS = 1_000_000_000


def _book(stamp: int, *, epoch: int = 1, spread_ticks: int = 1) -> BookState:
    bids = tuple((100.00 - 0.05 * level, 100 - 5 * level, 10 - level) for level in range(5))
    asks = tuple(
        (100.00 + 0.05 * spread_ticks + 0.05 * level, 80 - 3 * level, 8 - level)
        for level in range(5)
    )
    return BookState("full", stamp, stamp, epoch, bids, asks, 1, ())


def _observation(
    stamp: int,
    *,
    epoch: int = 1,
    target: float | None = 2.5,
    feature_shift: float = 0.0,
) -> HorseRaceObservation:
    features = {
        average_feature(window, depth): window + depth / 100.0 + feature_shift
        for window in OFI_WINDOWS_SECONDS
        for depth in OFI_DEPTHS
    }
    future = {} if target is None else {TARGET_HORIZON_SECONDS: target}
    return HorseRaceObservation(
        tape_index=1,
        run_id="fixture",
        receive_ts_ns=stamp,
        connection_epoch=epoch,
        features=features,
        future_ticks=future,
        past_ticks={seconds: -seconds for seconds in PRICE_LAG_SECONDS},
        same_window_ticks={},
        window_start_ts_ns={},
    )


def _surface(stamp: int, skew: float, *, epoch: int = 1, sequence: int = 1) -> FrameDraft:
    quality = {
        "quality__weighted_r_squared": 0.99,
        "quality__used_quote_count": 20.0,
        "quality__surface_age_seconds": 0.1,
        "quality__surface_is_stale": 0.0,
        "quality__arbitrage_passed": 1.0,
    }
    for expiry in EXPIRIES:
        quality[f"quality__{expiry.isoformat()}__quote_count"] = 5.0
        quality[f"quality__{expiry.isoformat()}__support_width"] = 0.2
    return FrameDraft(
        sequence=sequence,
        receive_ts_ns=stamp,
        connection_epoch=epoch,
        economic={surface_feature(EXPIRIES[0], "atm_skew"): skew},
        quality_numeric=quality,
        quality_categorical={"quality__smoothing_status": "smoothed"},
        surface_age_seconds=0.1,
        smoothing_status="smoothed",
    )


def _build(
    observations: list[HorseRaceObservation],
    *,
    books: list[BookState] | None = None,
    frames: list[FrameDraft] | None = None,
) -> FeatureConstructionResult:
    return build_feature_selection_rows(
        observations=observations,
        books=books or [],
        surface_frames=frames or [],
        session_open_ts_ns=0,
        session_close_ts_ns=1_000 * NS,
    )


def test_registry_is_unique_versioned_and_covers_every_frozen_axis() -> None:
    registry = build_registry()
    assert registry.version == REGISTRY_VERSION
    assert len(registry.feature_names) == len(set(registry.feature_names))
    assert {item.family for item in registry.features} == {
        "price_path",
        "book_liquidity",
        "ofi",
        "surface",
        "surface_quality",
        "time_regime",
        "interaction",
    }
    for window in OFI_WINDOWS_SECONDS:
        for depth in OFI_DEPTHS:
            assert average_feature(window, depth) in registry.feature_names
    for seconds in PRICE_LAG_SECONDS:
        assert price_lag_feature(seconds) in registry.feature_names
    assert set(INTERACTION_FEATURE_NAMES) <= set(registry.feature_names)
    target = registry.targets[0]
    assert target.causal_gap_seconds == CAUSAL_GAP_SECONDS
    assert target.horizon_seconds == TARGET_HORIZON_SECONDS
    assert target.reference_price == "displayed_bbo_mid"


def test_target_geometry_and_canonical_sources_are_exact() -> None:
    anchor = 20 * NS
    result = _build(
        [_observation(anchor)],
        books=[_book(anchor)],
        frames=[_surface(19 * NS, -0.2)],
    )
    row = result.rows[0]
    assert row.target_ticks == 2.5
    assert row.target_start_ts_ns == anchor + int(0.5 * NS)
    assert row.target_end_ts_ns == anchor + int(10.5 * NS)
    assert row.feature_values[price_lag_feature(10.0)] == -10.0
    assert row.feature_values[average_feature(10.0, 200)] == 12.0
    assert row.feature_values["lob__spread_ticks"] == pytest.approx(1.0)
    assert row.registry_version == REGISTRY_VERSION
    assert row.evidence_label == EVIDENCE_LABEL
    assert all(
        stamp is None or stamp <= row.anchor_ts_ns for stamp in row.feature_available_ts_ns.values()
    )


def test_surface_ew_innovation_uses_strictly_earlier_frames_and_future_is_irrelevant() -> None:
    first = _surface(5 * NS, -0.20, sequence=1)
    second = _surface(15 * NS, -0.10, sequence=2)
    future = _surface(25 * NS, 99.0, sequence=3)
    observations = [_observation(10 * NS), _observation(20 * NS)]
    books = [_book(10 * NS), _book(20 * NS)]
    without_future = _build(observations, books=books, frames=[first, second])
    with_future = _build(observations, books=books, frames=[first, second, future])
    name = surface_innovation_feature(surface_feature(EXPIRIES[0], "atm_skew"))
    assert without_future.rows[0].feature_values[name] is None
    assert without_future.rows[1].feature_values[name] == pytest.approx(0.10)
    assert with_future.rows[0].feature_values == without_future.rows[0].feature_values
    assert with_future.rows[1].feature_values == without_future.rows[1].feature_values
    assert SURFACE_EW_ALPHA == 0.2


def test_asof_join_never_crosses_connection_epoch_and_missingness_propagates() -> None:
    anchor = 20 * NS
    result = _build(
        [_observation(anchor, epoch=2)],
        books=[_book(anchor, epoch=1)],
        frames=[_surface(19 * NS, -0.2, epoch=1)],
    )
    row = result.rows[0]
    assert row.feature_values["lob__spread_ticks"] is None
    assert row.feature_values["quality__weighted_r_squared"] is None
    assert row.feature_values["interaction__ofi_w10_m10_x_spread"] is None
    assert row.feature_available_ts_ns["interaction__ofi_w10_m10_x_spread"] is None
    assert result.diagnostics["rows_without_book_features"] == 1
    assert result.diagnostics["rows_without_surface_features"] == 1


def test_missing_target_is_counted_and_not_fabricated() -> None:
    result = _build([_observation(20 * NS, target=None)])
    assert result.rows == ()
    assert result.diagnostics["missing_target_rows"] == 1
    assert result.diagnostics["confirmatory_eligible"] is False


def test_intraday_cycle_and_predeclared_interactions_are_deterministic() -> None:
    anchor = 250 * NS
    result = _build(
        [_observation(anchor)],
        books=[_book(anchor)],
        frames=[_surface(200 * NS, -0.2), _surface(240 * NS, -0.1, sequence=2)],
    )
    values = result.rows[0].feature_values
    ofi = values[average_feature(10.0, 10)]
    assert ofi is not None
    spread = values["regime__spread_ticks"]
    depth = values["lob__l1_total_quantity"]
    assert spread is not None and depth is not None
    assert values["interaction__ofi_w10_m10_x_spread"] == pytest.approx(ofi * spread)
    assert values["interaction__ofi_w10_m10_x_inverse_l1_depth"] == pytest.approx(ofi / depth)
    sine = values["regime__session_phase_sin"]
    cosine = values["regime__session_phase_cos"]
    assert sine is not None and cosine is not None
    assert sine**2 + cosine**2 == pytest.approx(1.0)
    assert math.isfinite(values["regime__abs_lag_return_10s_per_sqrt_second"] or math.nan)


def test_quality_gate_catches_deliberate_future_leakage_without_zero_fill() -> None:
    result = _build(
        [_observation(20 * NS + index * NS, feature_shift=float(index)) for index in range(4)],
        books=[_book(20 * NS + index * NS, spread_ticks=index + 1) for index in range(4)],
        frames=[_surface(19 * NS, -0.2)],
    )
    leaked = average_feature(10.0, 10)
    availability = result.rows[1].feature_available_ts_ns
    assert isinstance(availability, dict)
    availability[leaked] = result.rows[1].anchor_ts_ns + 1
    artifact = apply_feature_quality_gates(result, training_row_indices=(0, 1, 2))
    assert any(
        finding.reason == "future_availability"
        and finding.feature_name == leaked
        and finding.row_index == 1
        for finding in artifact.findings
    )
    assert artifact.rows[1].feature_values[leaked] is None
    assert not artifact.rows[1].missing_indicators[leaked]
    assert not artifact.rows[1].validity_indicators[leaked]
    assert leaked not in artifact.eligible_features


def test_surface_fit_support_and_freshness_gate_invalidates_surface_only() -> None:
    frame = _surface(19 * NS, -0.2)
    quality = frame.quality_numeric
    assert isinstance(quality, dict)
    quality["quality__surface_age_seconds"] = 600.0
    quality["quality__surface_is_stale"] = 1.0
    quality["quality__weighted_r_squared"] = 0.5
    quality["quality__used_quote_count"] = 2.0
    quality["quality__arbitrage_passed"] = 0.0
    result = _build(
        [_observation(20 * NS + index * NS, feature_shift=float(index**2)) for index in range(3)],
        books=[_book(20 * NS + index * NS, spread_ticks=index + 1) for index in range(3)],
        frames=[frame],
    )
    config = FeatureQualityGateConfig(
        surface=SurfaceQualityGate(
            maximum_age_seconds=480.0,
            minimum_weighted_r_squared=0.9,
            minimum_used_quote_count=10.0,
        )
    )
    artifact = apply_feature_quality_gates(result, training_row_indices=(0, 1, 2), config=config)
    reasons = {finding.reason for finding in artifact.findings}
    assert {
        "stale_availability",
        "surface_marked_stale",
        "surface_fit_below_minimum",
        "surface_support_below_minimum",
        "surface_arbitrage_failed",
    } <= reasons
    surface_name = surface_feature(EXPIRIES[0], "atm_skew")
    assert all(row.feature_values[surface_name] is None for row in artifact.rows)
    assert artifact.rows[0].feature_values[average_feature(0.5, 1)] is not None


def test_training_only_missing_constant_and_duplicate_gates_are_auditable() -> None:
    result = _build(
        [_observation(20 * NS + index * NS, feature_shift=float(index)) for index in range(4)],
        books=[_book(20 * NS + index * NS, spread_ticks=index + 1) for index in range(4)],
        frames=[_surface(19 * NS, -0.2)],
    )
    constant = price_lag_feature(0.5)
    duplicate = price_lag_feature(1.0)
    missing = price_lag_feature(2.0)
    for index, row in enumerate(result.rows):
        values = row.feature_values
        availability = row.feature_available_ts_ns
        assert isinstance(values, dict) and isinstance(availability, dict)
        values[constant] = 7.0 if index < 3 else 99.0
        values[duplicate] = float(index)
        values[price_lag_feature(5.0)] = float(index)
        values[missing] = None if index < 2 else float(index)
        availability[missing] = None if index < 2 else row.anchor_ts_ns
    artifact = apply_feature_quality_gates(
        result,
        training_row_indices=(0, 1, 2),
        config=FeatureQualityGateConfig(minimum_training_coverage=0.5),
    )
    by_feature = {(item.reason, item.feature_name) for item in artifact.findings}
    assert ("near_constant_training_feature", constant) in by_feature
    assert ("insufficient_training_coverage", missing) in by_feature
    assert (
        "exact_duplicate_training_feature",
        price_lag_feature(5.0),
    ) in by_feature
    assert constant not in artifact.eligible_features
    assert artifact.rows[3].feature_values[constant] is None


def test_schema_range_and_reproducibility_artifact_are_explicit() -> None:
    result = _build(
        [_observation(20 * NS + index * NS, feature_shift=float(index)) for index in range(3)],
        books=[_book(20 * NS + index * NS, spread_ticks=index + 1) for index in range(3)],
        frames=[_surface(19 * NS, -0.2)],
    )
    first_values = result.rows[0].feature_values
    first_availability = result.rows[0].feature_available_ts_ns
    second_values = result.rows[1].feature_values
    assert isinstance(first_values, dict)
    assert isinstance(first_availability, dict)
    assert isinstance(second_values, dict)
    first_values["unexpected"] = 1.0
    first_availability["unexpected"] = result.rows[0].anchor_ts_ns
    second_values["regime__minutes_from_open"] = -1.0
    first = apply_feature_quality_gates(result, training_row_indices=(0, 1, 2))
    second = apply_feature_quality_gates(result, training_row_indices=(0, 1, 2))
    assert first.input_fingerprint_sha256 == second.input_fingerprint_sha256
    assert first.eligible_features == second.eligible_features
    assert any(item.reason == "schema_extra_feature" for item in first.findings)
    assert any(
        item.reason == "range_violation" and item.feature_name == "regime__minutes_from_open"
        for item in first.findings
    )
