from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
import pytest

from shaurya.data.depth_thinning_analysis import DEPTH20, DEPTH200, BookState, parse_receive_ts_ns
from shaurya.signals.deep_book_normal_activity import SplitIndex
from shaurya.signals.ofi_horserace import (
    BANDS,
    MINIMUM_TRADE_PACKETS,
    MODEL_ORDER,
    OFI_WINDOWS_SECONDS,
    RETURN_HORIZONS_SECONDS,
    HorseRaceObservation,
    adjusted_band_feature,
    assert_no_lookahead,
    build_horserace_observations,
    build_trade_series,
    cks_feature,
    evaluate_cells,
    model_features,
    pk_band_feature,
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
        "trade_classifier_version": "quote-mid-tick-v1",
        "trade_alignment_version": "latest-complete-depth-before-print-v1",
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
    for lower, upper in BANDS:
        flow = final.features[pk_band_feature(0.5, lower, upper)]
        adjusted = final.features[adjusted_band_feature(0.5, lower, upper)]
        assert abs(adjusted) <= abs(flow) or flow == 0
    assert final.features[trade_feature(10.0)] == 0.0  # no print in the final 10 seconds
    assert_no_lookahead(observations)


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
        features[cks_feature(window)] = signal * 3
        for band_index, band in enumerate(BANDS, start=1):
            features[pk_band_feature(window, *band)] = signal * band_index
            features[adjusted_band_feature(window, *band)] = signal / band_index
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
    assert all(row["training_standardisation"]["source"] == "training_only" for row in rows)
    assert all(set(row["per_tape"]) == {"0", "1"} for row in rows)


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


def test_depth_adjusted_features_remain_finite() -> None:
    observation = _synthetic_observation(3)
    values = [
        observation.features[adjusted_band_feature(window, *band)]
        for window in OFI_WINDOWS_SECONDS
        for band in BANDS
    ]
    assert np.isfinite(values).all()
