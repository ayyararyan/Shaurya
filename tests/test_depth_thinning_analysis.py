"""DAT-20 correctness tests for the activity-thinning versus feed-loss measurements."""

from __future__ import annotations

from typing import Any

from shaurya.data.depth_thinning_analysis import (
    DEPTH20,
    DEPTH200,
    FULL,
    activity_by_distance,
    agreement_pass,
    build_states,
    change_rate_by_level,
    containment_pass,
    crossing_level,
    duration_matched_skip_test,
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
        ] + [
            {"price": round(99.90 - 0.05 * offset, 2), "quantity": 50, "orders": 1}
            for offset in range(18)
        ]
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
    bids = [
        {"price": round(100.0 - 0.05 * index, 2), "quantity": 10, "orders": 1} for index in range(5)
    ]
    asks = [
        {"price": round(100.05 + 0.05 * index, 2), "quantity": 10, "orders": 1}
        for index in range(5)
    ]
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


def test_float32_full_prices_are_quantised_before_cross_tier_comparison() -> None:
    # Regression for a DAT-20 measurement bug found on the first run-1 pass: the Full packet
    # encodes 5-level prices as binary32 and the depth channels as binary64, so raw float
    # equality reported 0/791 price agreement for reasons that had nothing to do with the book.
    full_row = {
        "event_type": FULL,
        "receive_ts": _ts(100),
        "receive_sequence": 2,
        "connection_epoch": 1,
        "update_side": "both",
        "bids": [{"price": 24118.900390625, "quantity": 65, "orders": 1}],
        "asks": [{"price": 24127.599609375, "quantity": 260, "orders": 4}],
        "quality_flags": [],
    }
    depth200_row = {
        "event_type": DEPTH200,
        "receive_ts": _ts(0),
        "receive_sequence": 1,
        "connection_epoch": 1,
        "update_side": "bid",
        "bids": [{"price": 24118.9, "quantity": 65, "orders": 1}],
        "asks": [{"price": 24127.6, "quantity": 260, "orders": 4}],
        "quality_flags": [],
    }
    result = agreement_pass(
        build_states([full_row], FULL), build_states([depth200_row], DEPTH200), 1, label="test"
    )
    assert result["comparisons"] == 1
    assert result["pass_a_strict_backward"]["all_levels_all_fields_equal"]["rate"] == 1.0


def test_a_one_tick_price_difference_still_registers_after_quantisation() -> None:
    full_row = {
        "event_type": FULL,
        "receive_ts": _ts(100),
        "receive_sequence": 2,
        "connection_epoch": 1,
        "update_side": "both",
        "bids": [{"price": 24118.95, "quantity": 65, "orders": 1}],
        "asks": [{"price": 24127.6, "quantity": 260, "orders": 4}],
        "quality_flags": [],
    }
    depth200_row = {
        "event_type": DEPTH200,
        "receive_ts": _ts(0),
        "receive_sequence": 1,
        "connection_epoch": 1,
        "update_side": "bid",
        "bids": [{"price": 24118.9, "quantity": 65, "orders": 1}],
        "asks": [{"price": 24127.6, "quantity": 260, "orders": 4}],
        "quality_flags": [],
    }
    result = agreement_pass(
        build_states([full_row], FULL), build_states([depth200_row], DEPTH200), 1, label="test"
    )
    assert result["pass_a_strict_backward"]["all_levels_price_equal"]["rate"] == 0.0


def _state_rows(event_type: str, milliseconds: int, sequence: int, bids, asks):
    return {
        "event_type": event_type,
        "receive_ts": _ts(milliseconds),
        "receive_sequence": sequence,
        "connection_epoch": 1,
        "update_side": "bid",
        "bids": [{"price": p, "quantity": q, "orders": o} for p, q, o in bids],
        "asks": [{"price": p, "quantity": q, "orders": o} for p, q, o in asks],
        "quality_flags": [],
    }


def test_containment_holds_when_the_deep_feed_has_an_extra_level() -> None:
    # depth200 carries an extra price point at 99.97 that depth20 lacks. Positional comparison
    # would mismatch every level below it; containment must still report full containment,
    # zero missing levels, and one extra level inside the witness range.
    depth20 = build_states(
        [
            _state_rows(
                DEPTH20, 100, 2, [(100.0, 10, 1), (99.95, 10, 1)], [(100.05, 10, 1), (100.1, 10, 1)]
            )
        ],
        DEPTH20,
    )
    depth200 = build_states(
        [
            _state_rows(
                DEPTH200,
                0,
                1,
                [(100.0, 10, 1), (99.97, 5, 1), (99.95, 10, 1)],
                [(100.05, 10, 1), (100.1, 10, 1)],
            )
        ],
        DEPTH200,
    )
    result = containment_pass(depth20, depth200, 2, label="test")
    assert result["pairs"] == 1
    bid = result["by_side"]["bid"]
    assert bid["price_containment"]["p50"] == 1.0
    assert bid["triple_containment"]["p50"] == 1.0
    assert bid["missing_prices"]["max"] == 0
    assert bid["extra_prices_inside_witness_range"]["max"] == 1
    assert bid["positional_prefix_match"]["max"] == 1


def test_containment_fails_when_the_cheaper_tier_has_a_level_the_deep_feed_lacks() -> None:
    # This is the F2-relevant case: depth20 published a price depth200 never carried.
    depth20 = build_states(
        [
            _state_rows(
                DEPTH20, 100, 2, [(100.0, 10, 1), (99.95, 10, 1)], [(100.05, 10, 1), (100.1, 10, 1)]
            )
        ],
        DEPTH20,
    )
    depth200 = build_states(
        [
            _state_rows(
                DEPTH200, 0, 1, [(100.0, 10, 1), (99.90, 10, 1)], [(100.05, 10, 1), (100.1, 10, 1)]
            )
        ],
        DEPTH200,
    )
    result = containment_pass(depth20, depth200, 2, label="test")
    bid = result["by_side"]["bid"]
    assert bid["missing_prices"]["max"] == 1
    assert bid["price_containment"]["p50"] == 0.5
    assert bid["pairs_with_full_price_containment"] == 0


def test_activity_by_distance_is_price_keyed_and_survives_a_positional_cascade() -> None:
    # A single insertion at the top shifts every deeper level by one position. The positional
    # measurement must call that a change at every level; the price-keyed measurement must not
    # attribute any activity to the untouched deep price points.
    far_bids = [(99.0 - 0.05 * index, 10, 1) for index in range(10)]
    first = _state_rows(
        DEPTH200, 0, 1, [(100.0, 10, 1), *far_bids], [(105.0, 10, 1), (105.05, 10, 1)]
    )
    second = _state_rows(
        DEPTH200,
        200,
        2,
        [(100.0, 10, 1), (99.5, 7, 1), *far_bids],
        [(105.0, 10, 1), (105.05, 10, 1)],
    )
    states = build_states([first, second], DEPTH200)
    positional = change_rate_by_level([first, second], "bid", levels=12)
    # Positional: the inserted level makes positions 2 onward all differ.
    assert positional["per_level"][1]["changed_publications"] == 1
    assert positional["per_level"][5]["changed_publications"] == 1

    price_keyed = activity_by_distance(states, "bid")
    total = sum(band["total_events"] for band in price_keyed["bands"])
    # Price-keyed: exactly one event, the insertion. No deep price point moved.
    assert total == 1
    assert sum(band["insertions"] for band in price_keyed["bands"]) == 1
    assert sum(band["modifications"] for band in price_keyed["bands"]) == 0
    assert sum(band["deletions"] for band in price_keyed["bands"]) == 0


def test_activity_by_distance_detects_genuine_thinning() -> None:
    # Near price points churn every publication; far price points never move. The normalised
    # per-price-point rate must therefore fall with distance and Spearman must be negative.
    rows = []
    for index in range(11):
        # Band [0,1): churns every publication. Band [1,2): churns every second publication.
        # Bands further out never move. Three populated bands are the minimum for Spearman.
        near = [(100.0, 10 + index, 1)]
        middle = [(99.0, 20 + index // 2, 2)]
        outer = [(97.0, 5, 1)]
        far = [(90.0 - 0.05 * offset, 5, 1) for offset in range(20)]
        rows.append(
            _state_rows(
                DEPTH200, index * 200, index + 1, [*near, *middle, *outer, *far], [(100.5, 10, 1)]
            )
        )
    states = build_states(rows, DEPTH200)
    result = activity_by_distance(states, "bid")
    correlation = result["spearman_band_index_vs_events_per_price_point"]
    assert correlation is not None and correlation < 0
    near_band = next(b for b in result["bands"] if b["band_rupees"] == "[0,1)")
    far_band = next(
        b for b in result["bands"] if b["total_events"] == 0 and b["price_point_exposure"]
    )
    assert near_band["events_per_second_per_price_point"] > 0
    assert far_band["events_per_second_per_price_point"] == 0.0


def test_boundary_exclusion_suppresses_ladder_window_slide_artifacts() -> None:
    # The ladder is a fixed-length sliding window. A genuine insertion at the top pushes the
    # deepest level out of the window, and that eviction is not an order-book event. Raw counting
    # sees one insertion plus one spurious deletion; boundary exclusion must keep the real
    # insertion and drop the eviction.
    first = _state_rows(
        DEPTH200,
        0,
        1,
        [(round(100.0 - 0.05 * index, 2), 10, 1) for index in range(10)],
        [(105.0, 10, 1)],
    )
    second = _state_rows(
        DEPTH200,
        200,
        2,
        [(round(100.05 - 0.05 * index, 2), 10, 1) for index in range(10)],
        [(105.0, 10, 1)],
    )
    states = build_states([first, second], DEPTH200)
    raw = activity_by_distance(states, "bid", exclude_boundary_levels=0)
    trimmed = activity_by_distance(states, "bid", exclude_boundary_levels=5)
    assert sum(band["insertions"] for band in raw["bands"]) == 1
    assert sum(band["deletions"] for band in raw["bands"]) == 1
    assert sum(band["insertions"] for band in trimmed["bands"]) == 1
    assert sum(band["deletions"] for band in trimmed["bands"]) == 0


def test_same_side_best_reference_moves_exposure_out_of_the_empty_near_mid_bands() -> None:
    # With a wide spread, mid-keyed banding leaves the innermost band empty and puts the best
    # quote several rupees out. Same-side-best keying must place the best quote in band [0,1).
    rows = [
        _state_rows(
            DEPTH200,
            index * 200,
            index + 1,
            [(100.0, 10 + index, 1), (99.5, 10, 1)],
            [(110.0, 10, 1)],
        )
        for index in range(5)
    ]
    states = build_states(rows, DEPTH200)
    mid_keyed = activity_by_distance(states, "bid", reference="mid")
    best_keyed = activity_by_distance(states, "bid", reference="same_side_best")
    mid_near = next(b for b in mid_keyed["bands"] if b["band_rupees"] == "[0,1)")
    best_near = next(b for b in best_keyed["bands"] if b["band_rupees"] == "[0,1)")
    assert mid_near["price_point_exposure"] == 0
    assert best_near["price_point_exposure"] > 0
    assert best_near["modifications"] == 4


def test_duration_matched_test_finds_no_effect_when_the_interior_state_is_redundant() -> None:
    # depth200 ticks every 200 ms with an unchanging book. A 400 ms skip and a 400 ms span that
    # contains an interior publication must both score zero unseen states.
    rows = []
    for index in range(21):
        if index == 5:
            continue  # the skipped tick
        rows.append(
            _state_rows(DEPTH200, index * 200, index + 1, [(100.0, 10, 1)], [(100.5, 10, 1)])
        )
    depth200 = build_states(rows, DEPTH200)
    witnesses = build_states(
        [
            _state_rows(FULL, milliseconds, 500 + milliseconds, [(100.0, 10, 1)], [(100.5, 10, 1)])
            for milliseconds in range(100, 4000, 137)
        ],
        FULL,
    )
    result = duration_matched_skip_test(depth200, witnesses, 1, "all_levels_price_equal")
    without = result["arms"]["no_interior_publication"]
    with_interior = result["arms"]["with_interior_publication"]
    assert without["spans"] == 1
    assert with_interior["spans"] > 0
    assert without["unseen_state_rate"] == 0.0
    assert with_interior["unseen_state_rate"] == 0.0


def test_duration_matched_test_detects_a_state_only_the_skipped_tick_could_have_shown() -> None:
    # The book is at 100.0 except in the 400 ms skip gap, where a witness sees 101.0. The
    # no-interior arm must record the unseen state; the with-interior arm must not.
    rows = []
    for index in range(21):
        if index == 5:
            continue
        rows.append(
            _state_rows(DEPTH200, index * 200, index + 1, [(100.0, 10, 1)], [(100.5, 10, 1)])
        )
    depth200 = build_states(rows, DEPTH200)
    witnesses = build_states(
        [
            _state_rows(FULL, 900, 900, [(101.0, 10, 1)], [(101.5, 10, 1)]),
            _state_rows(FULL, 2100, 2100, [(100.0, 10, 1)], [(100.5, 10, 1)]),
            _state_rows(FULL, 2300, 2300, [(100.0, 10, 1)], [(100.5, 10, 1)]),
        ],
        FULL,
    )
    result = duration_matched_skip_test(depth200, witnesses, 1, "all_levels_price_equal")
    assert result["arms"]["no_interior_publication"]["unseen"] == 1
    assert result["arms"]["with_interior_publication"]["unseen"] == 0


def test_occupied_level_index_at_a_rupee_distance_is_measured_not_assumed() -> None:
    # A contiguous 0.05-tick bid ladder of 40 levels spans exactly Rs 1.95 from the best bid, so
    # Rs 1.00 out must be the 21st occupied level and Rs 5.00 must be recorded as out of reach.
    bids = [(round(100.0 - 0.05 * index, 2), 10, 1) for index in range(40)]
    row = _state_rows(DEPTH200, 0, 1, bids, [(100.05, 10, 1)])
    states = build_states([row], DEPTH200)
    result = occupancy_and_span(states)
    within = result["occupied_levels_within_rupees_of_same_side_best"]["bid"]
    assert within["1"]["p50"] == 21
    assert within["1"]["instants_ladder_did_not_reach_this_distance"] == 0
    assert within["5"]["n"] == 0
    assert within["5"]["instants_ladder_did_not_reach_this_distance"] == 1


def test_cumulative_event_share_within_distance_is_reported() -> None:
    rows = [
        _state_rows(
            DEPTH200,
            index * 200,
            index + 1,
            [(100.0, 10 + index, 1), (50.0, 10, 1)],
            [(100.5, 10, 1)],
        )
        for index in range(5)
    ]
    states = build_states(rows, DEPTH200)
    result = activity_by_distance(states, "bid", reference="same_side_best")
    # All four modifications sit on the best bid, so everything is inside Rs 1.
    assert result["total_events"] == 4
    assert result["cumulative_event_share_within_distance"]["within_1_rupees"] == 1.0
    assert result["cumulative_event_share_within_distance"]["within_20_rupees"] == 1.0
