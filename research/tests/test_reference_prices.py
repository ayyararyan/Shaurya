"""Tests for `D38 / TOUCH-METRICS-2026-08-20` sections A.3 and A.4.

`VAL-TOUCH-03` — every reference price in the ladder produces a complete, comparable cell set —
is the frozen acceptance test here; `VAL-TOUCH-02` is re-asserted at the re-derivation boundary,
where a fallback to the displayed touch would be easiest to introduce by accident.
"""

from __future__ import annotations

import pytest

from shaurya.analytics.depth_thinning_analysis import DEPTH20, BookState
from shaurya.signals.effective_touch import EffectiveTouch, EffectiveTouchSeries, TradePrint
from shaurya.signals.reference_prices import (
    BASELINE_REFERENCE,
    REFERENCE_OBJECT_CATEGORY,
    REFERENCE_PRICE_LADDER,
    TOUCH_RELATIVE_BAND_TICKS,
    PricePath,
    ReferencePrice,
    build_displayed_mid_path,
    build_effective_touch_mid_path,
    build_last_trade_path,
    build_microprice_path,
    build_reference_price_paths,
    reference_price_coverage,
    touch_relative_metadata,
    touch_relative_microprice_tilt_ticks,
    touch_relative_queue_imbalance,
    touch_relative_state,
)

SECOND = 1_000_000_000


def _state(index: int, *, bid: float = 100.0, ask: float = 101.0, levels: int = 20) -> BookState:
    return BookState(
        channel=DEPTH20,
        receive_ts_ns=index * SECOND,
        receive_sequence=index,
        connection_epoch=1,
        bids=tuple((bid - 0.05 * level, 100 + level, 1) for level in range(levels)),
        asks=tuple((ask + 0.05 * level, 100 + level, 1) for level in range(levels)),
        rows_in_burst=1,
        quality_flags=(),
    )


def _print(index: int, price: float, side: str | None) -> TradePrint:
    return TradePrint(
        receive_ts_ns=index * SECOND,
        price=price,
        quantity=10.0,
        side=side,
        displayed_bid=None,
        displayed_ask=None,
        quote_channel=None,
        quote_age_ms=None,
        location=None,
        spread_ticks=None,
        degraded=False,
        coalesced=False,
    )


def _touch(bid: float | None, ask: float | None, *, anchor: int = 10 * SECOND) -> EffectiveTouch:
    return EffectiveTouch(
        window_seconds=10.0,
        anchor_ts_ns=anchor,
        effective_bid=bid,
        effective_ask=ask,
        buy_prints=1 if ask is not None else 0,
        sell_prints=1 if bid is not None else 0,
        newest_print_ts_ns=anchor - SECOND,
        crossed=bool(bid is not None and ask is not None and bid >= ask),
    )


# ----------------------------------------------------------------------------------- TOUCH-03


def test_price_path_refuses_to_extrapolate_past_either_edge() -> None:
    path = PricePath("test", (1 * SECOND, 2 * SECOND), (100.0, 100.5))
    assert path.as_of(0) is None
    assert path.as_of(1 * SECOND) == pytest.approx(100.0)
    assert path.as_of(int(1.5 * SECOND)) == pytest.approx(100.0)
    assert path.as_of(3 * SECOND) is None
    # a right-edge endpoint must be missing, not silently resolved back to the last observation
    assert path.return_ticks(1 * SECOND, 3 * SECOND) is None
    assert path.return_ticks(1 * SECOND, 2 * SECOND) == pytest.approx(10.0)
    # a non-advancing interval is not a return
    assert path.return_ticks(2 * SECOND, 2 * SECOND) is None


def test_displayed_mid_and_microprice_paths_differ_only_by_the_size_weighting() -> None:
    states = [_state(index) for index in range(3)]
    mid = build_displayed_mid_path(states)
    micro = build_microprice_path(states)
    assert mid.reference == ReferencePrice.DISPLAYED_MID.value
    assert micro.reference == ReferencePrice.MICROPRICE.value
    assert len(mid) == len(micro) == 3
    assert mid.as_of(SECOND) == pytest.approx(100.5)
    # bid queue 100, ask queue 100 at level one, so the microprice sits on the mid
    assert micro.as_of(SECOND) == pytest.approx(100.5)


def test_microprice_path_leans_with_the_level_one_queues() -> None:
    heavy_bid = BookState(
        channel=DEPTH20,
        receive_ts_ns=SECOND,
        receive_sequence=1,
        connection_epoch=1,
        bids=((100.0, 900, 1),),
        asks=((101.0, 100, 1),),
        rows_in_burst=1,
        quality_flags=(),
    )
    micro = build_microprice_path([heavy_bid])
    value = micro.as_of(SECOND)
    assert value is not None and 100.5 < value < 101.0


def test_last_trade_path_is_the_only_observed_member_of_the_ladder() -> None:
    path = build_last_trade_path([_print(2, 100.4, "buy"), _print(1, 100.2, "sell")])
    assert path.reference == ReferencePrice.LAST_TRADE.value
    assert path.as_of(1 * SECOND) == pytest.approx(100.2)
    assert path.as_of(2 * SECOND) == pytest.approx(100.4)
    assert REFERENCE_OBJECT_CATEGORY[ReferencePrice.LAST_TRADE.value] == "observed"


def test_effective_touch_path_skips_anchors_where_the_touch_is_undefined() -> None:
    prints = [_print(1, 100.2, "sell"), _print(2, 100.8, "buy")]
    series = EffectiveTouchSeries(prints, window_seconds=5.0)
    anchors = [3 * SECOND, 4 * SECOND, 60 * SECOND]
    path = build_effective_touch_mid_path(series, anchors)
    # the 60 s anchor has no print inside its window, so it contributes nothing at all
    assert len(path) == 2
    assert path.as_of(3 * SECOND) == pytest.approx(100.5)
    assert path.coverage_end_ts_ns == 4 * SECOND
    # past the last defined anchor the path is uncovered, not carried forward
    assert path.as_of(60 * SECOND) is None


def test_val_touch_03_the_full_ladder_is_built_and_reported_side_by_side() -> None:
    states = [_state(index) for index in range(5)]
    prints = [_print(1, 100.2, "sell"), _print(2, 100.8, "buy")]
    series = EffectiveTouchSeries(prints, window_seconds=5.0)
    paths = build_reference_price_paths(
        depth20_states=states,
        prints=prints,
        effective_touch=series,
        anchors=[3 * SECOND, 4 * SECOND],
    )
    assert sorted(paths) == sorted(REFERENCE_PRICE_LADDER)
    report = reference_price_coverage(paths)
    assert report["requirement"] == "TOUCH-03"
    assert report["ladder"] == list(REFERENCE_PRICE_LADDER)
    assert report["baseline_reference"] == BASELINE_REFERENCE
    assert report["applied_on_both_sides_of_the_regression"] is True
    assert all(report["paths"][name]["points"] > 0 for name in REFERENCE_PRICE_LADDER)
    assert report["paths"][ReferencePrice.EFFECTIVE_TOUCH_MID.value]["object_category"] == "proxy"


def test_val_touch_03_an_incomplete_ladder_is_refused() -> None:
    with pytest.raises(ValueError):
        reference_price_coverage({ReferencePrice.DISPLAYED_MID.value: PricePath("x", (), ())})


# ----------------------------------------------------------------------------------- TOUCH-04


def test_touch_relative_state_keys_bands_by_distance_from_the_effective_touch() -> None:
    state = _state(1, bid=100.0, ask=101.0, levels=20)
    # an effective touch sitting exactly on the displayed quote isolates the band arithmetic
    rekeyed = touch_relative_state(
        state, _touch(100.0, 101.0), levels=3, band_ticks=TOUCH_RELATIVE_BAND_TICKS
    )
    assert rekeyed is not None
    assert len(rekeyed.bids) == 3 and len(rekeyed.asks) == 3
    # band one runs [0, 5) ticks outward, so it holds displayed levels 0 to 4 on each side
    assert rekeyed.bids[0][0] == pytest.approx(100.0)
    assert rekeyed.bids[0][1] == 100 + 101 + 102 + 103 + 104
    assert rekeyed.asks[0][0] == pytest.approx(101.0)
    assert rekeyed.asks[0][1] == 100 + 101 + 102 + 103 + 104
    # band two is the next five ticks outward, and the representative price steps with it
    assert rekeyed.bids[1][0] == pytest.approx(100.0 - 5 * 0.05)
    assert rekeyed.bids[1][1] == 105 + 106 + 107 + 108 + 109
    assert rekeyed.receive_ts_ns == state.receive_ts_ns

    # moving the effective touch inside the displayed quote pushes the same depth outward
    shifted = touch_relative_state(state, _touch(100.5, 100.6), levels=3, band_ticks=5.0)
    assert shifted is not None
    assert shifted.bids[0][1] == 0
    assert shifted.bids[2][1] == 100 + 101 + 102 + 103 + 104


def test_touch_relative_state_excludes_displayed_depth_inside_the_effective_touch() -> None:
    # the effective touch is *outside* the displayed quote here, so displayed level one lies
    # strictly inside it and must not be folded into band one
    state = _state(1, bid=100.0, ask=101.0, levels=3)
    touch = _touch(99.0, 102.0)
    rekeyed = touch_relative_state(state, touch, levels=4, band_ticks=5.0)
    assert rekeyed is not None
    assert sum(level[1] for level in rekeyed.bids) == 0
    assert sum(level[1] for level in rekeyed.asks) == 0


def test_val_touch_02_re_derivation_never_falls_back_to_the_displayed_touch() -> None:
    state = _state(1)
    for touch in (
        _touch(None, 100.6),
        _touch(100.5, None),
        _touch(None, None),
        _touch(101.0, 100.0),
    ):
        assert touch_relative_state(state, touch, levels=3) is None
        assert touch_relative_queue_imbalance(state, touch) is None
        assert touch_relative_microprice_tilt_ticks(state, touch) is None


def test_touch_relative_state_validates_its_grid() -> None:
    state = _state(1)
    touch = _touch(100.5, 100.6)
    with pytest.raises(ValueError):
        touch_relative_state(state, touch, levels=0)
    with pytest.raises(ValueError):
        touch_relative_state(state, touch, levels=3, band_ticks=0.0)


def test_touch_relative_queue_imbalance_measures_depth_beside_the_effective_touch() -> None:
    heavier_bid = BookState(
        channel=DEPTH20,
        receive_ts_ns=SECOND,
        receive_sequence=1,
        connection_epoch=1,
        bids=((100.0, 300, 1), (99.0, 900, 1)),
        asks=((101.0, 100, 1), (102.0, 2_000, 1)),
        rows_in_burst=1,
        quality_flags=(),
    )
    touch = _touch(100.5, 100.6)
    # a 25-tick band from 100.50 down reaches 99.25, so the 99.00 level is outside it; likewise
    # 100.60 up to 101.85 excludes 102.00.  Only the near levels count.
    value = touch_relative_queue_imbalance(heavier_bid, touch, band_ticks=25.0)
    assert value == pytest.approx((300 - 100) / 400)
    # widen the band and the far levels enter, flipping the sign
    wide = touch_relative_queue_imbalance(heavier_bid, touch, band_ticks=60.0)
    assert wide is not None and wide < 0.0


def test_touch_relative_queue_imbalance_is_missing_when_the_band_is_empty() -> None:
    empty = BookState(
        channel=DEPTH20,
        receive_ts_ns=SECOND,
        receive_sequence=1,
        connection_epoch=1,
        bids=((50.0, 100, 1),),
        asks=((200.0, 100, 1),),
        rows_in_burst=1,
        quality_flags=(),
    )
    assert touch_relative_queue_imbalance(empty, _touch(100.5, 100.6), band_ticks=5.0) is None


def test_touch_relative_microprice_tilts_towards_the_thinner_effective_side() -> None:
    state = BookState(
        channel=DEPTH20,
        receive_ts_ns=SECOND,
        receive_sequence=1,
        connection_epoch=1,
        bids=((100.0, 900, 1),),
        asks=((101.0, 100, 1),),
        rows_in_burst=1,
        quality_flags=(),
    )
    tilt = touch_relative_microprice_tilt_ticks(state, _touch(100.5, 100.6), band_ticks=25.0)
    assert tilt is not None and tilt > 0.0


def test_touch_relative_metadata_states_what_it_removes_and_what_it_introduces() -> None:
    metadata = touch_relative_metadata()
    assert metadata["requirement"] == "TOUCH-04"
    assert metadata["object_category"] == "proxy"
    assert metadata["undefined_touch"].startswith("propagated_as_missing")
    assert "ID-CCZ-01" in metadata["removes"]
    assert metadata["limitation_id"] == "ID-TOUCH-01"
    assert set(metadata["re_derived"]) == {
        "ccz_multi_level_ofi",
        "l1_queue_imbalance",
        "microprice",
    }
