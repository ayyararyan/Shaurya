from __future__ import annotations

from shaurya.data.cadence_analysis import analyze_cadence


def _row(timestamp: str, bid: float, quantity: int) -> dict[str, object]:
    return {
        "event_type": "full",
        "receive_ts": timestamp,
        "best_bid": bid,
        "best_ask": 101.0,
        "bids": [{"price": bid, "quantity": quantity, "orders": 1}] * 5,
        "asks": [{"price": 101.0, "quantity": 10, "orders": 1}] * 5,
    }


def test_analyze_cadence_groups_exact_receive_timestamps() -> None:
    rows = [
        _row("2026-08-19T06:00:00.000000+00:00", 100.0, 10),
        _row("2026-08-19T06:00:00.000000+00:00", 100.0, 11),
        _row("2026-08-19T06:00:00.500000+00:00", 100.0, 12),
        _row("2026-08-19T06:00:01.000000+00:00", 100.5, 12),
    ]

    result = analyze_cadence(rows, "full")

    assert result.rows == 4
    assert result.bursts == 3
    assert result.gaps == 2
    assert result.window_seconds == 1.0
    assert result.burst_rate_per_second == 2.0
    assert result.rows_per_burst_mean == 4 / 3
    assert result.gap_p05_ms == 500.0
    assert result.gap_p50_ms == 500.0
    assert result.gap_p95_ms == 500.0
    assert result.modal_gap_bin_ms == "[500,550)"
    assert result.top_price_change_bursts == 1
    assert result.top_field_change_bursts == 2
    assert result.complete_five_level_rows == 4
