"""Acceptance probes for D39's fixed target and bounce corrections."""

from __future__ import annotations

from math import sin

import pytest

from shaurya.signals.ccz_ofi import level_feature, normalised_level_feature
from shaurya.signals.effective_touch import TradePrint
from shaurya.signals.fixed_target_panel import (
    TRADE_SIGN_CORRECTED,
    build_fixed_target_panel,
    build_same_side_print_path,
    build_trade_sign_corrected_path,
    competitor_features,
    make_return_resolver,
    roll_effective_spread,
)
from shaurya.signals.ofi_horserace import (
    HorseRaceObservation,
    HorseRaceTapeInput,
    cks_feature,
    normalised_trade_feature,
    touch_relative_feature,
)
from shaurya.signals.reference_prices import PricePath

SECOND = 1_000_000_000


def _print(index: int, price: float, side: str) -> TradePrint:
    return TradePrint(
        receive_ts_ns=index * SECOND,
        price=price,
        quantity=1.0,
        side=side,
        displayed_bid=99.0,
        displayed_ask=101.0,
        quote_channel="depth20",
        quote_age_ms=1.0,
        location=None,
        spread_ticks=40.0,
        degraded=False,
        coalesced=False,
    )


def test_val_bounce_01_alternating_prints_identify_a_positive_roll_spread() -> None:
    prints = [
        _print(index, 101.0 if index % 2 == 0 else 99.0, "buy" if index % 2 == 0 else "sell")
        for index in range(20)
    ]
    estimate = roll_effective_spread(prints)
    assert estimate.first_order_autocovariance_ticks2 is not None
    assert estimate.first_order_autocovariance_ticks2 < 0.0
    assert estimate.first_order_autocorrelation == pytest.approx(-1.0)
    assert estimate.effective_half_spread_ticks == pytest.approx(40.0)
    assert estimate.effective_spread_ticks == pytest.approx(80.0)


def test_val_bounce_02_signed_correction_removes_a_constant_half_spread() -> None:
    prints = [
        _print(1, 101.0, "buy"),
        _print(2, 99.0, "sell"),
        _print(3, 101.0, "buy"),
    ]
    path = build_trade_sign_corrected_path(prints, effective_half_spread_ticks=20.0)
    assert path.reference == TRADE_SIGN_CORRECTED
    assert path.prices == pytest.approx((100.0, 100.0, 100.0))
    assert path.return_ticks(SECOND, 3 * SECOND) == pytest.approx(0.0)


def test_val_bounce_03_same_side_endpoints_never_mix_sides() -> None:
    path = build_same_side_print_path(
        [
            _print(1, 101.0, "buy"),
            _print(2, 99.0, "sell"),
            _print(3, 102.0, "buy"),
            _print(4, 98.0, "sell"),
        ]
    )
    # Start resolves to the buy at t=1; the sell at t=2 is ignored and the buy at t=3 is used.
    assert path.return_ticks(SECOND, 3 * SECOND) == pytest.approx(20.0)
    # No later buy has printed by t=2, so a buy-to-sell mixed endpoint is refused.
    assert path.return_ticks(SECOND, 2 * SECOND) is None


def _observation(index: int) -> HorseRaceObservation:
    lagged = sin(index / 13.0)
    ofi = sin(index / 7.0 + 0.3)
    target = 0.65 * lagged + 0.55 * ofi
    past_target = sin(index / 19.0 + 1.7)
    window = 1.0
    scaled = normalised_level_feature(window, 1, 1)
    raw = level_feature(window, 1)
    features = {
        "spread_ticks": 2.0,
        "log1p_l1_depth": 5.0 + 0.01 * sin(index),
        "l1_queue_imbalance": 0.2 * sin(index / 5.0),
        "microprice_tilt_ticks": 0.1 * sin(index / 3.0),
        normalised_trade_feature(window): 0.3 * sin(index / 11.0),
        cks_feature(window): 0.4 * sin(index / 9.0),
        raw: 2.0 * ofi,
        scaled: ofi,
        touch_relative_feature("l1_queue_imbalance"): 0.15 * sin(index / 5.0),
        touch_relative_feature("microprice_tilt_ticks"): 0.08 * sin(index / 3.0),
        touch_relative_feature(scaled): 0.9 * ofi,
    }
    return HorseRaceObservation(
        tape_index=0,
        run_id="synthetic-d39",
        receive_ts_ns=index * SECOND,
        features=features,
        future_ticks={1.0: target},
        past_ticks={1.0: lagged if index % 2 else past_target},
        same_window_ticks={1.0: lagged},
        window_start_ts_ns={1.0: (index - 1) * SECOND + 1},
        connection_epoch=1,
        reference_future_ticks={},
        reference_past_ticks={},
        reference_same_window_ticks={},
    )


def test_val_d39_03_c12_is_the_exact_union_of_lagged_return_and_c8() -> None:
    c8 = competitor_features("C8", 1.0, 1)
    c12 = competitor_features("C12", 1.0, 1)
    assert c12 == ("__lagged__", *c8)


def test_val_d39_02_lagged_return_resolves_only_the_past_window() -> None:
    observation = _observation(10)
    resolver = make_return_resolver(
        "displayed_mid",
        corrected=PricePath(TRADE_SIGN_CORRECTED, (), ()),
        same_side=build_same_side_print_path([]),
    )
    assert resolver(observation, "past", 1.0) == observation.past_ticks[1.0]
    assert observation.window_start_ts_ns[1.0] <= observation.receive_ts_ns


def test_val_d39_04_every_estimated_competitor_uses_identical_rows_and_metrics() -> None:
    observations = tuple(_observation(index) for index in range(1, 601))
    tape = HorseRaceTapeInput(
        tape_index=0,
        run_id="synthetic-d39",
        instrument_id="NSE:NSE_FNO:NIFTY:future:2026-08-25",
        tape_sha256="0" * 64,
        observations=observations,
        depth200_publications=len(observations),
        depth20_publications=len(observations),
        observed_seconds=600.0,
        failures={},
    )
    prints = [
        _print(index, 101.0 if index % 2 == 0 else 99.0, "buy" if index % 2 == 0 else "sell")
        for index in range(1, 601)
    ]
    artifact = build_fixed_target_panel(
        tape,
        prints=prints,
        references=("displayed_mid",),
        levels=(1,),
        windows=(1.0,),
        horizons=(1.0,),
        replicates=0,
        seed=7,
    )
    cell = artifact["cells"][0]
    assert cell["status"] == "estimated"
    estimated = [row for row in cell["competitors"] if row["status"] == "estimated"]
    assert {row["competitor"] for row in estimated} == {f"C{index}" for index in range(13)}
    assert {row["row_hash"] for row in estimated} == {cell["common_test_row_hash"]}
    for row in estimated:
        assert row["test_n"] == cell["test_n"]
        assert set(row["metrics"]) >= {
            "information_coefficient",
            "sign_accuracy",
            "net_of_cost_pnl",
        }
    by_name = {row["competitor"]: row for row in estimated}
    # `VAL-D39-01`: the synthetic future OFI component is detected, while the deliberately
    # past-target-equal C2 arm trips the past-mirror guard.
    assert by_name["C8"]["absolute_oos_r2"] > 0.0
    assert by_name["C8"]["past_mirror_guard_passed"] is True
    assert by_name["C2"]["past_mirror_guard_passed"] is False
    assert cell["ofi_question"]["c12_incremental_oos_r2_over_c2"] > 0.0
