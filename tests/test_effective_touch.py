"""Acceptance and unit tests for `D38 / TOUCH-METRICS-2026-08-20` section A.

`VAL-TOUCH-01` (no print at or after the anchor may enter the estimate) and `VAL-TOUCH-02`
(an undefined effective touch propagates as missing and never as the displayed touch) are the
two frozen acceptance tests; the remainder pin the `TOUCH-01` classification rule and the
`TOUCH-02` coverage and staleness accounting.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from shaurya.data.depth_thinning_analysis import parse_receive_ts_ns
from shaurya.data.trade_direction import TRADE_ALIGNMENT_VERSION, TRADE_CLASSIFIER_VERSION
from shaurya.signals.effective_touch import (
    EFFECTIVE_TOUCH_WINDOWS_SECONDS,
    ID_TOUCH_01,
    NANOSECONDS_PER_SECOND,
    PRIMARY_EFFECTIVE_TOUCH_WINDOW,
    EffectiveTouchSeries,
    PrintLocation,
    TradePrint,
    build_trade_prints,
    classify_print_location,
    effective_touch_coverage,
    effective_touch_metadata,
    print_location_diagnostics,
    spread_bucket_label,
)

BASE = parse_receive_ts_ns("2026-08-20T03:51:46.000000+00:00")


def _iso(offset_ns: int) -> str:
    total = BASE + offset_ns
    seconds, remainder = divmod(total, NANOSECONDS_PER_SECOND)
    moment = datetime.fromtimestamp(seconds, tz=UTC).replace(microsecond=remainder // 1000)
    return moment.isoformat().replace("+00:00", "+00:00")


def _row(
    offset_ns: int,
    *,
    price: float,
    side: str = "buy",
    bid: float | None = 24251.0,
    ask: float | None = 24252.0,
    increment: int = 10,
    channel: str = "depth200",
    **overrides: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "event_type": "full",
        "receive_ts": _iso(offset_ns),
        "last_price": price,
        "last_quantity": 5,
        "cumulative_volume_increment": increment,
        "trade_side": side,
        "trade_quote_bid": bid,
        "trade_quote_ask": ask,
        "trade_quote_channel": channel,
        "trade_quote_age_ms": 12.0,
        "trade_classifier_version": TRADE_CLASSIFIER_VERSION,
        "trade_alignment_version": TRADE_ALIGNMENT_VERSION,
        "trade_classification_degraded": False,
        "trade_coalesced": False,
    }
    row.update(overrides)
    return row


def _print(offset_ns: int, price: float, side: str | None) -> TradePrint:
    return TradePrint(
        receive_ts_ns=BASE + offset_ns,
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


# ---------------------------------------------------------------------------------- TOUCH-01


def test_print_location_classification_is_on_the_quantised_tick_grid() -> None:
    # The Full packet encodes prices as binary32; the depth channels as binary64.  The same
    # exchange price must still compare equal at the touch.
    assert (
        classify_print_location(price=24252.900390625, displayed_bid=24251.0, displayed_ask=24252.9)
        is PrintLocation.AT_ASK
    )
    assert (
        classify_print_location(price=24251.0, displayed_bid=24251.0, displayed_ask=24252.9)
        is PrintLocation.AT_BID
    )
    assert (
        classify_print_location(price=24251.5, displayed_bid=24251.0, displayed_ask=24252.9)
        is PrintLocation.STRICTLY_INSIDE
    )
    assert (
        classify_print_location(price=24253.5, displayed_bid=24251.0, displayed_ask=24252.9)
        is PrintLocation.STRICTLY_OUTSIDE
    )
    assert (
        classify_print_location(price=24250.0, displayed_bid=24251.0, displayed_ask=24252.9)
        is PrintLocation.STRICTLY_OUTSIDE
    )


def test_print_location_refuses_a_crossed_or_locked_displayed_quote() -> None:
    with pytest.raises(ValueError):
        classify_print_location(price=100.0, displayed_bid=100.05, displayed_ask=100.0)
    with pytest.raises(ValueError):
        classify_print_location(price=100.0, displayed_bid=100.0, displayed_ask=100.0)


def test_spread_bucket_labels_are_half_open_with_an_open_final_bucket() -> None:
    assert spread_bucket_label(0.0) == "[0,2)"
    assert spread_bucket_label(2.0) == "[2,10)"
    assert spread_bucket_label(120.0) == "[100,150)"
    assert spread_bucket_label(10_000.0) == "[200,inf)"


def test_touch_01_reports_the_full_distribution_and_its_exclusion_accounting() -> None:
    rows = [
        _row(0, price=24251.5, side="buy"),
        _row(SECOND := NANOSECONDS_PER_SECOND, price=24251.0, side="sell"),
        _row(2 * SECOND, price=24252.0, side="buy"),
        _row(3 * SECOND, price=24255.0, side="buy"),
        # excluded: no volume increment
        _row(4 * SECOND, price=24251.5, increment=0),
        # retained as a print but has no usable displayed quote
        _row(5 * SECOND, price=24251.5, bid=None, ask=None),
        # excluded: wrong classifier version
        _row(6 * SECOND, price=24251.5, trade_classifier_version="wrong"),
        # excluded: missing alignment version
        {
            key: value
            for key, value in _row(7 * SECOND, price=24251.5).items()
            if key != "trade_alignment_version"
        },
    ]
    series = build_trade_prints(rows)
    assert len(series) == 5
    assert series.excluded_no_increment == 1
    assert series.excluded_wrong_classifier_version == 1
    assert series.excluded_missing_alignment_version == 1
    assert series.without_displayed_quote == 1

    report = print_location_diagnostics(series)
    assert report["requirement"] == "TOUCH-01"
    overall = report["overall"]
    assert overall["n"] == 4
    assert overall["counts"] == {
        "strictly_inside": 1,
        "at_bid": 1,
        "at_ask": 1,
        "strictly_outside": 1,
    }
    assert overall["inside_share"] == pytest.approx(0.25)
    assert overall["at_touch_share"] == pytest.approx(0.5)
    assert overall["outside_share"] == pytest.approx(0.25)
    assert report["prints_without_displayed_quote"] == 1
    assert report["by_ist_hour"]
    assert report["by_displayed_spread_bucket_ticks"]
    assert set(report["by_displayed_quote_channel"]) == {"depth200"}
    assert report["displayed_spread_ticks"]["p50"] == pytest.approx(20.0)
    assert report["id_cks_02_reference"]["tape_a_inside_share"] == pytest.approx(0.481)


def test_displayed_spread_ticks_are_measured_on_the_quantised_grid() -> None:
    # 24251.1 - 24251.0 is 0.09999999 in binary64, which is 1.9999 raw ticks and would fall in
    # the wrong bucket; the true exchange spread is exactly two ticks.
    series = build_trade_prints([_row(0, price=24251.05, bid=24251.0, ask=24251.1)])
    assert series.prints[0].spread_ticks == pytest.approx(2.0)
    assert spread_bucket_label(float(series.prints[0].spread_ticks or 0.0)) == "[2,10)"


def test_touch_01_buckets_by_hour_and_by_displayed_spread() -> None:
    hour = 3_600 * NANOSECONDS_PER_SECOND
    rows = [
        _row(0, price=24251.5, bid=24251.0, ask=24252.0),
        _row(hour, price=24251.05, bid=24251.0, ask=24251.1),
    ]
    report = print_location_diagnostics(build_trade_prints(rows))
    assert sorted(report["by_ist_hour"]) == ["09", "10"]
    assert sorted(report["by_displayed_spread_bucket_ticks"]) == ["[10,50)", "[2,10)"]


# ---------------------------------------------------------------------------------- TOUCH-02


def test_val_touch_01_estimate_never_uses_a_print_at_or_after_the_anchor() -> None:
    anchor = BASE + 10 * NANOSECONDS_PER_SECOND
    prints = [
        _print(9 * NANOSECONDS_PER_SECOND, 24252.0, "buy"),
        _print(9 * NANOSECONDS_PER_SECOND, 24251.0, "sell"),
        # a print stamped exactly at the anchor, and one after it, must both be invisible
        _print(10 * NANOSECONDS_PER_SECOND, 24240.0, "buy"),
        _print(11 * NANOSECONDS_PER_SECOND, 24239.0, "buy"),
        _print(10 * NANOSECONDS_PER_SECOND, 24260.0, "sell"),
    ]
    series = EffectiveTouchSeries(prints, window_seconds=5.0)
    touch = series.at(anchor)
    assert touch.effective_ask == pytest.approx(24252.0)
    assert touch.effective_bid == pytest.approx(24251.0)
    assert touch.buy_prints == 1
    assert touch.sell_prints == 1
    assert touch.newest_print_ts_ns == BASE + 9 * NANOSECONDS_PER_SECOND
    assert touch.staleness_ns == NANOSECONDS_PER_SECOND


def test_val_touch_01_holds_at_every_declared_window() -> None:
    anchor = BASE + 100 * NANOSECONDS_PER_SECOND
    prints = [
        _print(offset * NANOSECONDS_PER_SECOND, 24250.0 + offset, "buy" if offset % 2 else "sell")
        for offset in range(0, 130)
    ]
    for window in EFFECTIVE_TOUCH_WINDOWS_SECONDS:
        series = EffectiveTouchSeries(prints, window_seconds=window)
        touch = series.at(anchor)
        newest = touch.newest_print_ts_ns
        assert newest is None or newest < anchor


def test_val_touch_02_undefined_touch_is_missing_never_the_displayed_touch() -> None:
    anchor = BASE + 10 * NANOSECONDS_PER_SECOND
    # only buyer-initiated prints in the window: the bid side is undefined
    series = EffectiveTouchSeries(
        [_print(9 * NANOSECONDS_PER_SECOND, 24252.0, "buy")], window_seconds=5.0
    )
    touch = series.at(anchor)
    assert touch.effective_ask == pytest.approx(24252.0)
    assert touch.effective_bid is None
    assert not touch.defined
    assert touch.mid is None
    assert touch.spread_ticks is None

    # an empty window is undefined on both sides and reports no staleness
    empty = EffectiveTouchSeries([], window_seconds=5.0).at(anchor)
    assert empty.effective_bid is None and empty.effective_ask is None
    assert not empty.defined
    assert empty.mid is None
    assert empty.staleness_ns is None


def test_crossed_effective_bounds_are_undefined_and_counted() -> None:
    anchor = BASE + 10 * NANOSECONDS_PER_SECOND
    prints = [
        _print(8 * NANOSECONDS_PER_SECOND, 24251.0, "buy"),
        _print(9 * NANOSECONDS_PER_SECOND, 24253.0, "sell"),
    ]
    touch = EffectiveTouchSeries(prints, window_seconds=5.0).at(anchor)
    assert touch.crossed
    assert not touch.defined
    assert touch.mid is None

    coverage = effective_touch_coverage(EffectiveTouchSeries(prints, window_seconds=5.0), [anchor])
    assert coverage["crossed_anchors"] == 1
    assert coverage["coverage"] == pytest.approx(0.0)


def test_unsigned_prints_never_enter_the_effective_touch() -> None:
    anchor = BASE + 10 * NANOSECONDS_PER_SECOND
    prints = [
        _print(9 * NANOSECONDS_PER_SECOND, 24252.0, None),
        _print(9 * NANOSECONDS_PER_SECOND, 24251.0, "unclassified"),
    ]
    series = EffectiveTouchSeries(prints, window_seconds=5.0)
    assert series.buy_prints == 0 and series.sell_prints == 0
    assert not series.at(anchor).defined


def test_effective_touch_coverage_reports_staleness_and_missing_sides() -> None:
    prints = [
        _print(0, 24252.0, "buy"),
        _print(NANOSECONDS_PER_SECOND, 24251.0, "sell"),
    ]
    series = EffectiveTouchSeries(prints, window_seconds=5.0)
    anchors = [
        BASE + 2 * NANOSECONDS_PER_SECOND,
        BASE + 3 * NANOSECONDS_PER_SECOND,
        BASE + 60 * NANOSECONDS_PER_SECOND,
    ]
    coverage = effective_touch_coverage(series, anchors)
    assert coverage["requirement"] == "TOUCH-02"
    assert coverage["anchors"] == 3
    assert coverage["defined_anchors"] == 2
    assert coverage["coverage"] == pytest.approx(2 / 3)
    assert coverage["anchors_without_buy_print"] == 1
    assert coverage["anchors_without_sell_print"] == 1
    assert coverage["staleness_seconds"]["max"] == pytest.approx(2.0)
    assert coverage["effective_spread_ticks"]["p50"] == pytest.approx(20.0)
    assert coverage["undefined_is_missing_never_displayed_touch"] is True
    assert coverage["limitation_id"] == ID_TOUCH_01


def test_effective_touch_window_must_be_positive() -> None:
    with pytest.raises(ValueError):
        EffectiveTouchSeries([], window_seconds=0.0)


def test_effective_touch_metadata_labels_the_estimator_as_a_proxy() -> None:
    metadata = effective_touch_metadata()
    assert metadata["object_category"] == "proxy"
    assert metadata["primary_window_seconds"] == PRIMARY_EFFECTIVE_TOUCH_WINDOW
    assert metadata["declared_windows_seconds"] == list(EFFECTIVE_TOUCH_WINDOWS_SECONDS)
    assert "strictly prior prints only" in metadata["causality"]
    assert metadata["limitation_id"] == ID_TOUCH_01
