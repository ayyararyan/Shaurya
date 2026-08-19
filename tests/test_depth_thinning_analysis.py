"""DAT-20 correctness tests for the activity-thinning versus feed-loss measurements."""

from __future__ import annotations

from typing import Any

from shaurya.data.depth_thinning_analysis import (
    DEPTH20,
    DEPTH200,
    FULL,
    agreement_pass,
    build_states,
    change_rate_by_level,
    crossing_level,
    occupancy_and_span,
    skip_window_test,
    spearman,
)


def _ts(milliseconds: int) -> str:
    seconds, remainder = divmod(milliseconds, 1000)
    return f"2026-08-19T07:40:{seconds:02d}.{remainder:03d}000+00:00"


def _ladder(top: float, step: float, count: int, quantity: int = 100) -> list[dict[str, Any]]:
    return [
        {"price": round(top + step * index, 2), "quantity": quantity + index, "orders": 1 + index}
        for index in range(count)
    ]


def _row(
    event_type: str,
    milliseconds: int,
    sequence: int,
    *,
    side: str,
    bid_top: float = 100.0,
    ask_top: float = 100.05,
    levels: int = 20,
    bid_quantity: int = 100,
) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "receive_ts": _ts(milliseconds),
        "receive_sequence": sequence,
        "connection_epoch": 1,
        "update_side": side,
        "bids": _ladder(bid_top, -0.05, levels, bid_quantity),
        "asks": _ladder(ask_top, 0.05, levels),
        "quality_flags": [],
    }


def test_build_states_collapses_a_burst_to_one_state_and_keeps_merged_book() -> None:
    rows = [
        _row(DEPTH200, 0, 1, side="bid"),
        _row(DEPTH200, 0, 2, side="ask"),
        _row(DEPTH200, 200, 3, side="bid"),
        _row(DEPTH200, 200, 4, side="ask"),
    ]
    states = build_states(rows, DEPTH200)
    assert len(states) == 2
    assert states[0].rows_in_burst == 2
    assert states[0].best_bid == 100.0
    assert states[0].best_ask == 100.05
    assert states[1].receive_ts_ns > states[0].receive_ts_ns


def test_identical_books_agree_exactly_under_strict_backward_pass() -> None:
    depth200 = build_states(
        [_row(DEPTH200, 0, 1, side="bid"), _row(DEPTH200, 0, 2, side="ask")], DEPTH200
    )
    depth20 = build_states(
        [_row(DEPTH20, 100, 3, side="bid"), _row(DEPTH20, 100, 4, side="ask")], DEPTH20
    )
    result = agreement_pass(depth20, depth200, 20, label="test")
    assert result["comparisons"] == 1
    assert result["pass_a_strict_backward"]["all_levels_all_fields_equal"]["rate"] == 1.0
    assert result["comparand_age_ms"]["p50"] == 100.0


def test_a_pure_clock_phase_offset_is_classified_as_phase_not_content() -> None:
    # depth200 publishes state X at 0 ms and state Y at 300 ms. The depth20 witness at 200 ms
    # already shows Y. Strict backward comparison fails; the phase-tolerant pass must resolve it.
    depth200 = build_states(
        [
            _row(DEPTH200, 0, 1, side="bid", bid_top=100.0),
            _row(DEPTH200, 0, 2, side="ask"),
            _row(DEPTH200, 300, 5, side="bid", bid_top=100.10),
            _row(DEPTH200, 300, 6, side="ask", bid_top=100.10),
        ],
        DEPTH200,
    )
    depth20 = build_states(
        [
            _row(DEPTH20, 200, 3, side="bid", bid_top=100.10),
            _row(DEPTH20, 200, 4, side="ask", bid_top=100.10),
        ],
        DEPTH20,
    )
    result = agreement_pass(depth20, depth200, 20, label="test")
    strict = result["pass_a_strict_backward"]["all_levels_price_equal"]
    assert strict["agree"] == 0
    phase = result["pass_b_phase_tolerant"]["tolerance_250ms"]["all_levels_price_equal"]
    assert phase["resolved_by_phase"] == 1
    assert phase["genuine_content_difference"] == 0


def test_a_real_content_difference_survives_phase_tolerance() -> None:
    depth200 = build_states(
        [_row(DEPTH200, 0, 1, side="bid", bid_top=100.0), _row(DEPTH200, 0, 2, side="ask")],
        DEPTH200,
    )
    depth20 = build_states(
        [
            _row(DEPTH20, 100, 3, side="bid", bid_top=999.0),
            _row(DEPTH20, 100, 4, side="ask", bid_top=999.0),
        ],
        DEPTH20,
    )
    result = agreement_pass(depth20, depth200, 20, label="test")
    phase = result["pass_b_phase_tolerant"]["tolerance_500ms"]["all_levels_price_equal"]
    assert phase["genuine_content_difference"] == 1


def test_change_rate_decays_when_activity_concentrates_at_the_top() -> None:
    # Level 1 moves every publication, level 2 every second publication, levels 3+ never.
    # This is the shape H-DAT20 predicts, so the analyzer must recover it exactly.
    rows: list[dict[str, Any]] = []
    for index in range(11):
        bids = [
            {"price": 100.00, "quantity": 100 + index, "orders": 1},
            {"price": 99.95, "quantity": 100 + index // 2, "orders": 1},
        ] + [{"price": round(99.90 - 0.05 * offset, 2), "quantity": 50, "orders": 1} for offset in range(18)]
        rows.append(
            {
                "event_type": DEPTH200,
                "receive_ts": _ts(index * 200),
                "receive_sequence": index + 1,
                "connection_epoch": 1,
                "update_side": "bid",
                "bids": bids,
                "asks": _ladder(100.05, 0.05, 20),
                "quality_flags": [],
            }
        )
    curve = change_rate_by_level(rows, "bid", levels=20)
    per_level = curve["per_level"]
    assert curve["transitions"] == 10
    assert per_level[0]["changed_publications"] == 10
    assert per_level[1]["changed_publications"] == 5
    assert all(entry["changed_publications"] == 0 for entry in per_level[2:])
    rates = [entry["change_rate_per_second"] for entry in per_level]
    # Heavy ties in the flat deep tail attenuate Spearman toward zero; the coefficient is
    # therefore a conservative one-sided check for decay, never a measure of its magnitude.
    correlation = spearman(rates)
    assert correlation is not None and correlation < -0.5
    assert per_level[0]["inter_change_ms_median"] == 200.0
    assert per_level[1]["inter_change_ms_median"] == 400.0


def test_change_rate_is_zero_for_levels_that_never_move() -> None:
    static_ask = _ladder(100.05, 0.05, 20)
    rows = []
    for index in range(5):
        row = _row(DEPTH200, index * 200, index + 1, side="ask")
        row["asks"] = [dict(level) for level in static_ask]
        rows.append(row)
    curve = change_rate_by_level(rows, "ask", levels=20)
    assert all(entry["changed_publications"] == 0 for entry in curve["per_level"])
    assert crossing_level(curve["per_level"], 0.01) == 1


def test_crossing_level_requires_the_rate_to_stay_below_the_threshold() -> None:
    per_level = [
        {"level": 1, "change_rate_per_second": 3.0},
        {"level": 2, "change_rate_per_second": 0.5},
        {"level": 3, "change_rate_per_second": 2.5},
        {"level": 4, "change_rate_per_second": 0.2},
        {"level": 5, "change_rate_per_second": 0.1},
    ]
    assert crossing_level(per_level, 2.0) == 4


def test_spearman_detects_monotone_decay() -> None:
    assert spearman([10.0, 8.0, 6.0, 4.0, 2.0]) == -1.0
    assert spearman([2.0, 4.0, 6.0, 8.0, 10.0]) == 1.0


def test_skip_window_flags_a_state_the_deep_feed_never_published() -> None:
    # depth200 publishes X at 0 ms then X again at 500 ms (a skipped base tick). A Full witness
    # inside the window shows a third state Z. That is the F3 event: an unseen state.
    depth200 = build_states(
        [
            _row(DEPTH200, 0, 1, side="bid", bid_top=100.0),
            _row(DEPTH200, 0, 2, side="ask"),
            _row(DEPTH200, 500, 5, side="bid", bid_top=100.0),
            _row(DEPTH200, 500, 6, side="ask"),
        ],
        DEPTH200,
    )
    full = build_states([_row(FULL, 250, 3, side="both", bid_top=101.0, levels=5)], FULL)
    result = skip_window_test(depth200, full, 5, "all_levels_price_equal")
    assert result["skip_windows"]["windows"] == 1
    assert result["skip_windows"]["matches_neither_unseen_state"] == 1
    assert result["skip_windows"]["unseen_state_rate"] == 1.0
    assert result["control_windows"]["windows"] == 0


def test_skip_window_records_an_empty_skip_as_matching_both_endpoints() -> None:
    depth200 = build_states(
        [
            _row(DEPTH200, 0, 1, side="bid"),
            _row(DEPTH200, 0, 2, side="ask"),
            _row(DEPTH200, 500, 5, side="bid"),
            _row(DEPTH200, 500, 6, side="ask"),
        ],
        DEPTH200,
    )
    full = build_states([_row(FULL, 250, 3, side="both", levels=5)], FULL)
    result = skip_window_test(depth200, full, 5, "all_levels_price_equal")
    assert result["skip_windows"]["matches_open_and_close_identical"] == 1
    assert result["skip_windows"]["matches_neither_unseen_state"] == 0


def test_control_and_skip_windows_are_split_at_the_pre_registered_threshold() -> None:
    depth200 = build_states(
        [
            _row(DEPTH200, 0, 1, side="bid"),
            _row(DEPTH200, 200, 2, side="bid"),
            _row(DEPTH200, 700, 3, side="bid"),
        ],
        DEPTH200,
    )
    result = skip_window_test(depth200, [], 5, "all_levels_price_equal")
    assert result["control_windows"]["windows"] == 1
    assert result["skip_windows"]["windows"] == 1


def test_occupancy_measures_span_and_contiguity_without_assuming_either() -> None:
    bids = [{"price": round(100.0 - 0.05 * index, 2), "quantity": 10, "orders": 1} for index in range(5)]
    asks = [{"price": round(100.05 + 0.05 * index, 2), "quantity": 10, "orders": 1} for index in range(5)]
    row = {
        "event_type": DEPTH200,
        "receive_ts": _ts(0),
        "receive_sequence": 1,
        "connection_epoch": 1,
        "update_side": "bid",
        "bids": bids,
        "asks": asks,
        "quality_flags": [],
    }
    states = build_states([row], DEPTH200)
    result = occupancy_and_span(states)
    assert result["populated_levels"]["bid"]["p50"] == 5
    # Contiguous ticks: 5 levels across a 0.20 rupee range is exactly 5 ticks.
    assert result["contiguity_ratio_populated_over_tick_span"]["bid"]["p50"] == 1.0
    assert result["missing_ticks_within_span"]["bid"]["max"] == 0
    assert abs(result["rupees_mid_to_deepest"]["bid"]["p50"] - 0.225) < 1e-9


def test_gapped_levels_are_detected_rather_than_assumed_contiguous() -> None:
    bids = [
        {"price": 100.00, "quantity": 10, "orders": 1},
        {"price": 99.95, "quantity": 10, "orders": 1},
        {"price": 99.50, "quantity": 10, "orders": 1},
    ]
    asks = [{"price": 100.05, "quantity": 10, "orders": 1}]
    row = {
        "event_type": DEPTH200,
        "receive_ts": _ts(0),
        "receive_sequence": 1,
        "connection_epoch": 1,
        "update_side": "bid",
        "bids": bids,
        "asks": asks,
        "quality_flags": [],
    }
    states = build_states([row], DEPTH200)
    result = occupancy_and_span(states)
    # 3 populated levels spanning 0.50 rupees = 11 contiguous ticks, so 8 ticks are missing.
    assert result["missing_ticks_within_span"]["bid"]["max"] == 8
    assert result["contiguity_ratio_populated_over_tick_span"]["bid"]["p50"] < 0.3


def test_padding_levels_with_zero_price_are_excluded_from_occupancy() -> None:
    bids = [{"price": 100.0, "quantity": 10, "orders": 1}] + [
        {"price": 0.0, "quantity": 0, "orders": 0} for _ in range(3)
    ]
    asks = [{"price": 100.05, "quantity": 10, "orders": 1}]
    row = {
        "event_type": DEPTH200,
        "receive_ts": _ts(0),
        "receive_sequence": 1,
        "connection_epoch": 1,
        "update_side": "bid",
        "bids": bids,
        "asks": asks,
        "quality_flags": [],
    }
    states = build_states([row], DEPTH200)
    result = occupancy_and_span(states)
    assert result["populated_levels"]["bid"]["p50"] == 1
    assert result["padding_levels_zero_price"]["bid"] == 3


def test_stale_comparand_is_excluded_rather_than_silently_compared() -> None:
    depth200 = build_states(
        [_row(DEPTH200, 0, 1, side="bid"), _row(DEPTH200, 0, 2, side="ask")], DEPTH200
    )
    depth20 = build_states(
        [_row(DEPTH20, 2_000, 3, side="bid"), _row(DEPTH20, 2_000, 4, side="ask")], DEPTH20
    )
    result = agreement_pass(depth20, depth200, 20, label="test", staleness_bound_ms=1_000.0)
    assert result["comparisons"] == 0
    assert result["excluded_stale_comparand"] == 1
