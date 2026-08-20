from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
import pytest

from scripts.ofi_horserace import _ablation_csv, _gate_csv, _intensity_csv, _support_csv
from shaurya.data.depth_thinning_analysis import DEPTH20, DEPTH200, BookState, parse_receive_ts_ns
from shaurya.data.trade_direction import TRADE_ALIGNMENT_VERSION, TRADE_CLASSIFIER_VERSION
from shaurya.signals.ccz_ofi import (
    average_feature,
    best_level_feature,
    denominator_feature,
    fit_integrated_weights,
    level_feature,
    normalised_level_feature,
)
from shaurya.signals.deep_book_normal_activity import SplitIndex
from shaurya.signals.ofi_horserace import (
    CCZ_LEVEL_COUNTS,
    CCZ_PRIMARY_LEVELS,
    MINIMUM_TRADE_PACKETS,
    MODEL_ORDER,
    OFI_WINDOWS_SECONDS,
    RETURN_HORIZONS_SECONDS,
    HorseRaceObservation,
    _direction_by_tape,
    assert_no_lookahead,
    build_ccz_arm_design,
    build_horserace_observations,
    build_trade_series,
    ccz_feature_schema,
    ccz_normalised_features,
    ccz_raw_features,
    cks_feature,
    cks_pressure_feature,
    evaluate_ccz_aggregation_arms,
    evaluate_cells,
    evaluate_combined_ablations,
    evaluate_normalised_subarms,
    model_features,
    normalised_trade_feature,
    resolve_30_second_gate,
    select_ridge_alpha,
    trade_feature,
)

SECOND = 1_000_000_000
BASE = parse_receive_ts_ns("2026-08-19T07:39:35.000000+00:00")


def _state(
    index: int,
    *,
    channel: str = DEPTH200,
    bid_quantity: int = 100,
    ask_quantity: int = 100,
    bid: float = 100.0,
    ask: float = 100.05,
    epoch: int = 0,
) -> BookState:
    bids = tuple((bid - 0.05 * level, bid_quantity + level, 1) for level in range(200))
    asks = tuple((ask + 0.05 * level, ask_quantity + level, 1) for level in range(200))
    levels = 20 if channel == DEPTH20 else 200
    return BookState(
        channel=channel,
        receive_ts_ns=BASE + index * SECOND // 2,
        receive_sequence=index,
        connection_epoch=epoch,
        bids=bids[:levels],
        asks=asks[:levels],
        rows_in_burst=1,
        quality_flags=(),
    )


def _iso(index: int) -> str:
    seconds = 35 + index // 2
    minute = 39 + seconds // 60
    second = seconds % 60
    fraction = "500000" if index % 2 else "000000"
    return f"2026-08-19T07:{minute:02d}:{second:02d}.{fraction}+00:00"


def _trade_row(index: int, side: str, *, coalesced: bool = False) -> dict[str, Any]:
    return {
        "event_type": "full",
        "receive_ts": _iso(index),
        "cumulative_volume_increment": 10,
        "last_quantity": 4,
        "trade_side": side,
        "trade_classifier_version": TRADE_CLASSIFIER_VERSION,
        "trade_alignment_version": TRADE_ALIGNMENT_VERSION,
        "trade_coalesced": coalesced,
        "trade_classification_degraded": False,
    }


def test_signed_trade_series_uses_only_identified_last_print_quantity() -> None:
    rows = [_trade_row(index, "buy" if index % 2 == 0 else "sell") for index in range(40)]
    rows.append(_trade_row(41, "buy", coalesced=True))
    rows.append({**_trade_row(42, "unclassified"), "trade_classification_degraded": True})
    series = build_trade_series(rows)
    assert series.identified
    assert series.qualified_packets == 40
    assert series.excluded_coalesced == 1
    assert series.excluded_degraded_or_unclassified == 1
    signed, absolute = series.window(BASE - 1, BASE + 20 * SECOND)
    assert signed == 0.0
    assert absolute == 160.0


def test_absent_trade_schema_is_unidentified_not_fabricated_zero() -> None:
    series = build_trade_series([{"event_type": "full", "cumulative_volume_increment": 10}])
    assert not series.identified
    assert series.schema_packets == 0
    assert series.qualified_packets == 0


def test_trade_series_requires_exact_classifier_and_alignment_versions() -> None:
    rows = [_trade_row(index, "buy") for index in range(MINIMUM_TRADE_PACKETS)]
    rows.extend(
        [
            {**_trade_row(41, "buy"), "trade_classifier_version": "wrong"},
            {
                key: value
                for key, value in _trade_row(42, "buy").items()
                if key != "trade_classifier_version"
            },
            {**_trade_row(43, "buy"), "trade_alignment_version": "wrong"},
            {
                key: value
                for key, value in _trade_row(44, "buy").items()
                if key != "trade_alignment_version"
            },
            {**_trade_row(45, "buy"), "last_quantity": 0},
        ]
    )
    series = build_trade_series(rows)
    assert series.identified
    assert series.schema_packets == MINIMUM_TRADE_PACKETS + 5
    assert series.qualified_packets == MINIMUM_TRADE_PACKETS
    assert series.excluded_wrong_classifier_version == 1
    assert series.excluded_missing_classifier_version == 1
    assert series.excluded_wrong_alignment_version == 1
    assert series.excluded_missing_alignment_version == 1
    assert series.excluded_degraded_or_unclassified == 1


def test_construction_uses_canonical_cks_and_causal_depth_adjustment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    depth200 = [_state(index) for index in range(100)]
    # At the final state, add bid L1 and remove ask L1: canonical CKS is positive.
    depth200[-1] = _state(99, bid_quantity=110, ask_quantity=90)
    depth20 = [_state(index, channel=DEPTH20) for index in range(170)]
    rows = [_trade_row(index, "buy") for index in range(MINIMUM_TRADE_PACKETS + 5)]

    import shaurya.signals.ofi_horserace as module

    canonical = module.cks_l1_transition
    calls = 0

    def counted(previous: BookState, current: BookState) -> Any:
        nonlocal calls
        calls += 1
        return canonical(previous, current)

    monkeypatch.setattr(module, "cks_l1_transition", counted)
    observations, failures = build_horserace_observations(
        depth200_states=depth200,
        depth20_states=depth20,
        rows=rows,
        tape_index=0,
        run_id="test",
    )
    assert calls == len(depth200) - 1
    assert failures["trade_support"]["qualified_packets"] >= MINIMUM_TRADE_PACKETS
    final = observations[-1]
    assert final.features[cks_feature(0.5)] > 0
    assert final.features[cks_pressure_feature(0.5)] > 0
    # CCZ Eq. (3): one common denominator divides every level, so the ratio of any two scaled
    # levels equals the ratio of their raw flows.  A per-band denominator would break this.
    denominator = final.features[denominator_feature(0.5, CCZ_PRIMARY_LEVELS)]
    assert denominator > 0.0
    for level in range(1, CCZ_PRIMARY_LEVELS + 1):
        raw = final.features[level_feature(0.5, level)]
        scaled = final.features[normalised_level_feature(0.5, level, CCZ_PRIMARY_LEVELS)]
        assert scaled == pytest.approx(raw / denominator)
    assert final.features[trade_feature(10.0)] == 0.0  # no print in the final 10 seconds
    assert normalised_trade_feature(10.0) not in final.features
    assert_no_lookahead(observations)


def test_unsupported_level_count_is_missing_not_zero_filled() -> None:
    depth200 = [
        replace(_state(index), bids=_state(index).bids[:100], asks=_state(index).asks[:100])
        for index in range(100)
    ]
    depth20 = [_state(index, channel=DEPTH20) for index in range(170)]
    observations, failures = build_horserace_observations(
        depth200_states=depth200,
        depth20_states=depth20,
        rows=[_trade_row(index, "buy") for index in range(MINIMUM_TRADE_PACKETS + 5)],
        tape_index=0,
        run_id="shallow-book",
    )
    assert observations
    assert failures["ccz_level_support_missing"]["200"] > 0
    for observation in observations:
        for window in OFI_WINDOWS_SECONDS:
            # A hundred-level book supports every declared arm through M = 20 and none at 200.
            assert denominator_feature(window, 20) in observation.features
            assert denominator_feature(window, 200) not in observation.features
            # Raw levels are materialised only up to the deepest supported declared M.
            assert level_feature(window, 20) in observation.features
            assert level_feature(window, 21) not in observation.features


def test_no_lookahead_guard_rejects_open_boundary_or_future_window() -> None:
    observation = _synthetic_observation(0)
    bad = replace(observation, window_start_ts_ns={0.5: observation.receive_ts_ns})
    # The end instant is allowed as an event timestamp; a future timestamp is not.
    assert_no_lookahead([bad])
    with pytest.raises(AssertionError, match="future"):
        assert_no_lookahead(
            [replace(observation, window_start_ts_ns={0.5: observation.receive_ts_ns + 1})]
        )
    with pytest.raises(AssertionError, match="open boundary"):
        assert_no_lookahead(
            [
                replace(
                    observation,
                    window_start_ts_ns={0.5: observation.receive_ts_ns - SECOND // 2},
                )
            ]
        )


def _synthetic_observation(index: int, *, test_shift: float = 0.0) -> HorseRaceObservation:
    signal = float((index % 11) - 5)
    features: dict[str, float] = {
        "log1p_l1_depth": 5.0 + (index % 3) / 10,
        "spread_ticks": 1.0 + (index % 2),
        "l1_queue_imbalance": signal / 5,
    }
    for window in OFI_WINDOWS_SECONDS:
        features[trade_feature(window)] = signal * 2
        features[normalised_trade_feature(window)] = signal / 5
        features[cks_feature(window)] = signal * 3
        features[cks_pressure_feature(window)] = signal / 4
        for count in CCZ_LEVEL_COUNTS:
            features[denominator_feature(window, count)] = 40.0 + count
            features[average_feature(window, count)] = signal / (count + 1)
        features[best_level_feature(window)] = signal / 40.0
        for level in range(1, max(CCZ_LEVEL_COUNTS) + 1):
            features[level_feature(window, level)] = signal * level / 10.0
        for level in range(1, CCZ_PRIMARY_LEVELS + 1):
            features[normalised_level_feature(window, level, CCZ_PRIMARY_LEVELS)] = (
                signal * level / 500.0
            )
    targets = {
        horizon: 0.4 * signal + horizon / 20 + test_shift for horizon in RETURN_HORIZONS_SECONDS
    }
    return HorseRaceObservation(
        tape_index=index % 2,
        run_id=str(index % 2),
        receive_ts_ns=BASE + index * SECOND,
        features=features,
        future_ticks=targets,
        past_ticks={horizon: 0.7 * signal for horizon in RETURN_HORIZONS_SECONDS},
        same_window_ticks={window: signal for window in OFI_WINDOWS_SECONDS},
        window_start_ts_ns={
            window: BASE + index * SECOND - int(window * SECOND) + 1
            for window in OFI_WINDOWS_SECONDS
        },
    )


def test_model_labels_are_exact_and_m2_is_blocked_when_unidentified() -> None:
    assert tuple(model_features(model, 1.0, trade_identified=True) for model in MODEL_ORDER)
    assert model_features("M2", 1.0, trade_identified=False) == ()
    assert trade_feature(1.0) in model_features("M6", 1.0, trade_identified=True)
    assert trade_feature(1.0) not in model_features("M6", 1.0, trade_identified=False)


def test_ridge_selection_uses_training_only_and_is_deterministic() -> None:
    observations = [_synthetic_observation(index) for index in range(120)]
    train = tuple(range(90))
    names = model_features("M4", 1.0, trade_identified=True)
    first = select_ridge_alpha(observations, train, names=names, horizon=1.0, source="future")
    changed_test = observations[:90] + [
        _synthetic_observation(index, test_shift=1_000_000.0) for index in range(90, 120)
    ]
    second = select_ridge_alpha(changed_test, train, names=names, horizon=1.0, source="future")
    assert first == second


def test_gate_direction_uses_single_predictor_coefficient_not_fitted_covariance() -> None:
    observations: list[HorseRaceObservation] = []
    for index in range(80):
        observation = _synthetic_observation(index)
        sign = 1.0 if observation.tape_index == 0 else -1.0
        signal = observation.features[cks_feature(0.5)]
        observations.append(replace(observation, future_ticks={10.0: sign * signal}))
    directions = _direction_by_tape(
        observations,
        tuple(range(len(observations))),
        names=("log1p_l1_depth", "spread_ticks", cks_feature(0.5)),
        model="M3",
        horizon=10.0,
        source="future",
        alpha=0.0,
    )
    assert directions["0"] is not None and directions["0"] > 0
    assert directions["1"] is not None and directions["1"] < 0


def test_evaluation_emits_complete_common_sample_and_training_standardisation() -> None:
    observations = [_synthetic_observation(index) for index in range(120)]
    split = SplitIndex(
        train=tuple(range(80)),
        embargoed=tuple(range(80, 90)),
        test=tuple(range(90, 120)),
        embargo_seconds=120.0,
        boundaries=(),
    )
    rows = evaluate_cells(
        observations,
        split,
        horizons=(1.0,),
        source="future",
        trade_identified=True,
        replicates=3,
        seed=7,
    )
    assert len(rows) == len(OFI_WINDOWS_SECONDS) * len(MODEL_ORDER)
    assert {row["train_n"] for row in rows} == {80}
    assert {row["test_n"] for row in rows} == {30}
    assert {row["embargoed_n"] for row in rows} == {10}
    assert all(row["support_by_tape"]["0"]["train_n"] == 40 for row in rows)
    assert all(row["training_standardisation"]["source"] == "training_only" for row in rows)
    assert all(set(row["per_tape"]) == {"0", "1"} for row in rows)
    for row in rows:
        if row["model"] in {"M4", "M5"}:
            diagnostics = row["level_contribution_diagnostics"]
            assert len(diagnostics["levels"]) == CCZ_PRIMARY_LEVELS
            assert "held-out contribution" in diagnostics["definition"]
            assert all(level["test_n"] == 30 for level in diagnostics["levels"])
            assert [level["level"] for level in diagnostics["levels"]] == list(
                range(1, CCZ_PRIMARY_LEVELS + 1)
            )


def test_missing_scaled_level_enforces_primary_common_complete_case() -> None:
    observations = [_synthetic_observation(index) for index in range(120)]
    feature = normalised_level_feature(1.0, CCZ_PRIMARY_LEVELS, CCZ_PRIMARY_LEVELS)
    for index in range(0, len(observations), 4):
        features = dict(observations[index].features)
        del features[feature]
        observations[index] = replace(observations[index], features=features)
    split = SplitIndex(
        train=tuple(range(80)),
        embargoed=tuple(range(80, 90)),
        test=tuple(range(90, 120)),
        embargo_seconds=120.0,
        boundaries=(),
    )
    rows = evaluate_cells(
        observations,
        split,
        horizons=(1.0,),
        source="future",
        trade_identified=True,
        replicates=3,
        seed=11,
    )
    one_second = [row for row in rows if row["h1_seconds"] == 1.0]
    assert {row["train_n"] for row in one_second} == {60}
    assert {row["test_n"] for row in one_second} == {23}
    baseline = next(row for row in one_second if row["model"] == "M0")
    adjusted = next(row for row in one_second if row["model"] == "M5")
    assert baseline["support_loss_to_common_sample"]["total_n"] == 30
    assert adjusted["support_loss_to_common_sample"]["total_n"] == 0


def test_normalised_subarms_and_combined_ablations_are_complete() -> None:
    observations = [_synthetic_observation(index) for index in range(120)]
    split = SplitIndex(
        train=tuple(range(80)),
        embargoed=tuple(range(80, 90)),
        test=tuple(range(90, 120)),
        embargo_seconds=120.0,
        boundaries=(),
    )
    subarms = evaluate_normalised_subarms(
        observations,
        split,
        source="future",
        trade_identified=True,
        replicates=3,
        seed=17,
    )
    assert len(subarms) == 2 * len(OFI_WINDOWS_SECONDS) * len(RETURN_HORIZONS_SECONDS)
    assert {row["subarm"] for row in subarms} == {
        "M2b_normalised_trade",
        "M3b_depth_normalised_cks",
    }
    ablations = evaluate_combined_ablations(observations, split, trade_identified=True)
    assert len(ablations) == 5 * len(OFI_WINDOWS_SECONDS) * len(RETURN_HORIZONS_SECONDS)
    assert all(row["status"] == "estimated" for row in ablations)


def test_normalised_trade_subarm_uses_only_positive_denominator_support() -> None:
    observations = [_synthetic_observation(index) for index in range(120)]
    feature = normalised_trade_feature(1.0)
    for index in range(0, len(observations), 4):
        features = dict(observations[index].features)
        del features[feature]
        observations[index] = replace(observations[index], features=features)
    split = SplitIndex(
        train=tuple(range(80)),
        embargoed=tuple(range(80, 90)),
        test=tuple(range(90, 120)),
        embargo_seconds=120.0,
        boundaries=(),
    )
    rows = evaluate_normalised_subarms(
        observations,
        split,
        source="future",
        trade_identified=True,
        replicates=3,
        seed=23,
    )
    row = next(
        item
        for item in rows
        if item["subarm"] == "M2b_normalised_trade"
        and item["h1_seconds"] == 1.0
        and item["h2_seconds"] == 1.0
    )
    assert row["status"] == "estimated"
    assert row["total_n"] == 90
    assert row["train_n"] == 60
    assert row["test_n"] == 23


def test_compact_csv_artifacts_are_complete_and_deterministic() -> None:
    ablations = [
        {
            "h1_seconds": 1.0,
            "h2_seconds": 2.0,
            "excluded_family": "M1_static_queue",
            "status": "estimated",
            "family_incremental_oos_r2": 0.01,
        }
    ]
    intensities = [{"h1_seconds": 1.0, "feature": "x", "n": 3, "missing_n": 1, "mean": 0.5}]
    support = [
        {
            "source": "future",
            "category": "primary",
            "label": "M0",
            "h1_seconds": 1.0,
            "h2_seconds": 2.0,
            "status": "estimated",
            "common_test_n": 30,
        }
    ]
    gate = resolve_30_second_gate(
        [_gate_row("future", model, 0.2) for model in MODEL_ORDER[1:6]],
        [_gate_row("past", model, 0.1) for model in MODEL_ORDER[1:6]],
    )
    renderers = (
        (_ablation_csv, ablations, "excluded_family"),
        (_intensity_csv, intensities, "missing_n"),
        (_support_csv, support, "common_test_n"),
        (_gate_csv, gate, "all_conditions"),
    )
    for renderer, payload, required_header in renderers:
        first = renderer(payload)  # type: ignore[arg-type]
        assert first == renderer(payload)  # type: ignore[arg-type]
        assert required_header in first.splitlines()[0]
        assert len(first.splitlines()) >= 2


def _gate_row(
    source: str,
    model: str,
    increment: float,
    *,
    tape_increment: float = 0.1,
    directions: tuple[float, float] = (1.0, 2.0),
) -> dict[str, Any]:
    return {
        "source": source,
        "model": model,
        "h1_seconds": 1.0,
        "h2_seconds": 10.0,
        "status": "estimated",
        "incremental_oos_r2_over_m0": increment,
        "per_tape": {
            "0": {"incremental_oos_r2_over_m0": tape_increment},
            "1": {"incremental_oos_r2_over_m0": tape_increment},
        },
        "direction_by_tape": {"0": directions[0], "1": directions[1]},
    }


def test_30_second_gate_requires_all_four_conditions() -> None:
    future = [_gate_row("future", model, 0.2) for model in MODEL_ORDER[1:6]]
    past = [_gate_row("past", model, 0.1) for model in MODEL_ORDER[1:6]]
    passed = resolve_30_second_gate(future, past)
    assert passed["gate_passed"]
    failed_future = [dict(row) for row in future]
    failed_future[0] = _gate_row("future", "M1", 0.2, tape_increment=-0.01)
    for index in range(1, len(failed_future)):
        failed_future[index] = _gate_row("future", MODEL_ORDER[index + 1], 0.05)
    failed_past = [_gate_row("past", model, 0.1) for model in MODEL_ORDER[1:6]]
    failed = resolve_30_second_gate(failed_future, failed_past)
    assert not failed["gate_passed"]
    assert not failed["evaluated_candidates"][0]["conditions"]["per_tape_increment_non_negative"]


def test_fixed_seed_cell_output_is_deterministic() -> None:
    observations = [_synthetic_observation(index) for index in range(100)]
    split = SplitIndex(
        train=tuple(range(70)),
        embargoed=tuple(range(70, 80)),
        test=tuple(range(80, 100)),
        embargo_seconds=120.0,
        boundaries=(),
    )
    arguments = dict(
        horizons=(0.5,),
        source="future",
        trade_identified=True,
        replicates=3,
        seed=19,
    )
    first = evaluate_cells(observations, split, **arguments)  # type: ignore[arg-type]
    second = evaluate_cells(observations, split, **arguments)  # type: ignore[arg-type]
    assert first == second


def test_depth_scaled_features_remain_finite() -> None:
    observation = _synthetic_observation(3)
    values = [
        observation.features[name]
        for window in OFI_WINDOWS_SECONDS
        for name in ccz_normalised_features(window, CCZ_PRIMARY_LEVELS)
    ]
    assert np.isfinite(values).all()


def test_ccz_aggregation_arms_cover_every_declared_arm_and_level_count() -> None:
    """`EST-CCZ-05` and `EST-CCZ-06`: no declared arm or level count is dropped."""

    observations = [_synthetic_observation(index) for index in range(120)]
    split = SplitIndex(
        train=tuple(range(80)),
        embargoed=tuple(range(80, 90)),
        test=tuple(range(90, 120)),
        embargo_seconds=120.0,
        boundaries=(),
    )

    rows = evaluate_ccz_aggregation_arms(
        observations,
        split,
        horizons=(1.0,),
        level_counts=(1, 5, 10),
        replicates=3,
        seed=5,
    )

    assert {row["levels"] for row in rows} == {1, 5, 10}
    assert {row["arm"] for row in rows} == {
        "per_level_pi",
        "integrated",
        "simple_average",
        "best_level",
    }
    assert all(row["estimator"] == "CCZ" for row in rows)
    assert len(rows) == len(OFI_WINDOWS_SECONDS) * 3 * 4
    estimated = [row for row in rows if row["status"] == "estimated"]
    assert estimated
    assert all(0.0 <= row["explained_variance_ratio"] <= 1.0 for row in estimated)
    integrated = [row for row in estimated if row["arm"] == "integrated"]
    assert all(row["primary_arm"] for row in integrated)
    assert all(row["integrated_weights"]["fitted_on"] == "training_rows_only" for row in integrated)


def test_integrated_weights_ignore_test_rows_entirely() -> None:
    """`VAL-CCZ-04`: mutating held-out rows cannot move the fitted first component."""

    observations = [_synthetic_observation(index) for index in range(120)]
    train = tuple(range(80))
    design = build_ccz_arm_design(observations, train, window=1.0, levels=CCZ_PRIMARY_LEVELS)
    before = fit_integrated_weights(design.normalised)

    contaminated = list(observations)
    for index in range(90, 120):
        features = dict(contaminated[index].features)
        for level in range(1, CCZ_PRIMARY_LEVELS + 1):
            features[level_feature(1.0, level)] = 10_000.0
        contaminated[index] = replace(contaminated[index], features=features)
    after_design = build_ccz_arm_design(
        contaminated, train, window=1.0, levels=CCZ_PRIMARY_LEVELS
    )
    after = fit_integrated_weights(after_design.normalised)

    assert before.weights == after.weights


def test_feature_schema_declares_every_name_the_builder_writes() -> None:
    schema = ccz_feature_schema(CCZ_LEVEL_COUNTS)
    for window in OFI_WINDOWS_SECONDS:
        for name in (
            *ccz_raw_features(window, max(CCZ_LEVEL_COUNTS)),
            *ccz_normalised_features(window, CCZ_PRIMARY_LEVELS),
            best_level_feature(window),
            cks_feature(window),
        ):
            assert schema.position(name) is not None
