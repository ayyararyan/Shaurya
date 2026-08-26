from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from shaurya.contracts.tape import DepthLevel, TapeRow
from shaurya.contracts.timing import IST

from shaurya.analytics.alignment_analysis import analyze_tape_rows

BASE = datetime(2026, 8, 19, 10, 0, tzinfo=IST)
BID = (DepthLevel(100.0, 10, 1),)
ASK = (DepthLevel(101.0, 10, 1),)


def _row(
    sequence: int,
    milliseconds: int,
    event_type: str,
    *,
    update_side: str | None = None,
    bids: tuple[DepthLevel, ...] = (),
    asks: tuple[DepthLevel, ...] = (),
    last_price: float | None = None,
    last_quantity: int | None = None,
    cumulative_volume: int | None = None,
) -> TapeRow:
    return TapeRow(
        run_id="run",
        receive_sequence=sequence,
        connection_epoch=1,
        source="dhan",
        event_type=event_type,
        instrument_id="NSE:NSE_FNO:NIFTY:future:2026-08-25",
        broker_security_id="58072",
        exchange_segment="NSE_FNO",
        receive_ts=BASE + timedelta(milliseconds=milliseconds),
        raw_message_size_bytes=100,
        update_side=update_side,
        bids=bids,
        asks=asks,
        last_price=last_price,
        last_quantity=last_quantity,
        cumulative_volume=cumulative_volume,
    )


def _flip_tape() -> tuple[TapeRow, ...]:
    return (
        _row(1, 0, "depth20", update_side="bid", bids=BID),
        _row(2, 100, "depth20", update_side="ask", bids=BID, asks=ASK),
        _row(3, 150, "full", last_price=100.0, last_quantity=1, cumulative_volume=100),
        _row(4, 400, "full", last_price=100.75, last_quantity=4, cumulative_volume=110),
        _row(
            5,
            450,
            "depth20",
            update_side="bid",
            bids=(DepthLevel(100.8, 10, 1),),
            asks=ASK,
        ),
    )


def test_alignment_analysis_measures_age_proxy_flip_and_coalescing() -> None:
    result = analyze_tape_rows({"fixture": _flip_tape()})
    overall = result["overall"]
    assert overall["prints"] == 1
    assert overall["side_counts"] == {"buy": 1}
    assert overall["quote_age_ms"]["p50"] == pytest.approx(400.0)
    assert overall["post_quote_delay_ms"]["p50"] == pytest.approx(50.0)
    assert overall["directional_comparisons"] == 1
    assert overall["proxy_flip_count"] == 1
    assert overall["proxy_flip_rate"] == 1.0
    assert overall["coalesced_count"] == 1
    assert overall["coalesced_excess_units"]["p50"] == 6.0
    assert overall["last_quantity_volume_coverage"] == 0.4


def test_alignment_analysis_groups_activity_tier_time_and_retains_empty_tape() -> None:
    result = analyze_tape_rows({"empty": (), "fixture": _flip_tape()})
    assert set(result["by_depth_tier"]) == {"depth20"}
    assert set(result["by_tape"]) == {"fixture"}
    assert set(result["by_time_of_day"]) == {"morning_before_12"}
    assert set(result["by_activity_band"]) == {"active_ge_15_prints_per_min"}
    assert set(result["by_quote_age_band"]) == {"gt_250_le_500ms"}
    coverage = {item["path"]: item for item in result["tape_coverage"]}
    assert coverage["empty"]["rows"] == 0
    assert coverage["empty"]["positive_volume_prints"] == 0
    assert coverage["empty"]["print_rate_per_minute"] == 0
    assert coverage["fixture"]["depth_tiers"] == ("depth20",)


def test_alignment_analysis_exposes_missing_post_proxy_and_validates_horizon() -> None:
    rows = _flip_tape()[:-1]
    result = analyze_tape_rows({"fixture": rows}, post_quote_horizon_ms=10.0)
    assert result["overall"]["post_proxy_available"] == 0
    assert result["overall"]["directional_comparisons"] == 0
    assert result["overall"]["proxy_flip_rate"] is None
    with pytest.raises(ValueError, match="positive"):
        analyze_tape_rows({"fixture": rows}, post_quote_horizon_ms=0)


def test_post_proxy_requires_the_same_selected_depth_tier() -> None:
    rows = list(_flip_tape())
    rows[-1] = replace(rows[-1], event_type="depth200")
    result = analyze_tape_rows({"fixture": rows})
    assert result["overall"]["prints"] == 1
    assert result["overall"]["post_proxy_available"] == 0
    assert result["overall"]["proxy_flip_rate"] is None


def test_stale_quote_remains_degraded_and_outside_directional_flip_denominator() -> None:
    rows = (
        _row(1, 0, "depth20", update_side="bid", bids=BID),
        _row(2, 100, "depth20", update_side="ask", bids=BID, asks=ASK),
        _row(3, 150, "full", last_price=100.0, last_quantity=1, cumulative_volume=100),
        _row(4, 1500, "full", last_price=100.75, last_quantity=4, cumulative_volume=110),
    )
    result = analyze_tape_rows({"fixture": rows})
    assert result["overall"]["degraded_count"] == 1
    assert result["overall"]["reason_counts"] == {"stale_quote": 1}
    assert result["overall"]["directional_comparisons"] == 0
    assert result["by_quote_age_band"]["gt_500ms"]["prints"] == 1
