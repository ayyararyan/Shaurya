from __future__ import annotations

from dataclasses import fields, replace

import pytest

from shaurya.data.depth_thinning_analysis import DEPTH200, BookState
from shaurya.signals.deep_book_anomaly import (
    AtomicEventType,
    BaselineContext,
    PreviousSessionEmpiricalBaseline,
    detect_candidates,
)


def state(
    ts_ns: int,
    *,
    bids: list[tuple[float, int, int]] | None = None,
    asks: list[tuple[float, int, int]] | None = None,
    epoch: int = 1,
    flags: tuple[str, ...] = (),
) -> BookState:
    return BookState(
        channel=DEPTH200,
        receive_ts_ns=ts_ns,
        receive_sequence=ts_ns,
        connection_epoch=epoch,
        bids=tuple(bids or [(100.0, 10, 1), (70.0, 10, 1)]),
        asks=tuple(asks or [(101.0, 10, 1), (131.0, 10, 1)]),
        rows_in_burst=2,
        quality_flags=flags,
    )


def test_price_keying_turns_a_positional_cascade_into_one_addition() -> None:
    before = state(1, bids=[(100.0, 10, 1), (90.0, 10, 1), (70.0, 10, 1)])
    after = state(2, bids=[(100.0, 10, 1), (90.0, 10, 1), (79.0, 7, 1), (70.0, 10, 1)])

    result = detect_candidates(before, after, instrument_id="NIFTY-FUT")

    assert [(event.atomic_type, event.price) for event in result.candidates] == [
        (AtomicEventType.ADDITION, 79.0)
    ]


def test_quantity_and_order_count_changes_are_separate_atomic_events() -> None:
    before = state(1)
    after = state(
        2,
        bids=[(100.0, 10, 1), (70.0, 15, 3)],
        asks=[(101.0, 10, 1), (131.0, 10, 1)],
    )

    result = detect_candidates(before, after, instrument_id="NIFTY-FUT")

    assert {event.atomic_type for event in result.candidates} == {
        AtomicEventType.QUANTITY_INCREASE,
        AtomicEventType.ORDER_COUNT_INCREASE,
    }


def test_relocation_is_a_quantity_matched_proxy_and_not_double_counted() -> None:
    before = state(1, bids=[(100.0, 10, 1), (60.0, 100, 4)])
    after = state(2, bids=[(100.0, 10, 1), (75.0, 110, 5)])

    result = detect_candidates(before, after, instrument_id="NIFTY-FUT")

    assert len(result.candidates) == 1
    event = result.candidates[0]
    assert event.atomic_type is AtomicEventType.RELOCATION_TOWARD_TOUCH_PROXY
    assert event.source_price == 60.0
    assert event.price == 75.0
    assert event.magnitude == 100.0
    assert event.object_category == "proxy"


def test_near_complete_outer_window_slide_is_excluded() -> None:
    common = [(100.0 - index, 10, 1) for index in range(30)]
    before = state(1, bids=common + [(60.0, 8, 1)])
    after = state(2, bids=common + [(50.0, 8, 1)])

    result = detect_candidates(before, after, instrument_id="NIFTY-FUT")

    assert not result.candidates
    assert result.exclusions[0].reason == "whole_ladder_boundary_churn"
    assert set(result.exclusions[0].prices) == {50.0, 60.0}


@pytest.mark.parametrize("reason", ["connection_epoch_boundary", "invalid_quality:sequence_gap"])
def test_contaminated_transitions_are_rejected_whole(reason: str) -> None:
    before = state(1)
    after = (
        state(2, epoch=2) if reason.startswith("connection") else state(2, flags=("sequence_gap",))
    )

    result = detect_candidates(before, after, instrument_id="NIFTY-FUT")

    assert not result.candidates
    assert result.exclusions[0].reason == reason


def test_strict_far_boundary_uses_pre_event_same_side_best() -> None:
    asks = [(103.0, 10, 1), (133.0, 10, 1)]
    before = state(
        1,
        bids=[(100.0, 10, 1), (80.0, 10, 1), (79.95, 10, 1)],
        asks=asks,
    )
    after = state(
        2,
        bids=[(101.0, 10, 1), (80.0, 11, 1), (79.95, 11, 1)],
        asks=asks,
    )

    result = detect_candidates(before, after, instrument_id="NIFTY-FUT")

    assert [(event.price, event.distance_rupees) for event in result.candidates] == [(79.95, 20.05)]


def test_previous_session_baseline_never_learns_from_current_session() -> None:
    before = state(1)
    after = state(2, bids=[(100.0, 10, 1), (70.0, 20, 1)])
    candidate = detect_candidates(before, after, instrument_id="NIFTY-FUT").candidates[0]
    baseline = PreviousSessionEmpiricalBaseline(minimum_history=2, thresholds=(0.5, 0.9))
    day1 = BaselineContext("2026-08-20", 1, "09:30", "L1", "R1")
    day2 = BaselineContext("2026-08-21", 2, "09:30", "L1", "R1")
    day3 = BaselineContext("2026-08-22", 3, "09:30", "L1", "R1")

    first = baseline.score(replace(candidate, magnitude=5.0), day1)
    second = baseline.score(replace(candidate, magnitude=10.0), day1)
    third = baseline.score(replace(candidate, magnitude=20.0), day2)
    fourth = baseline.score(replace(candidate, magnitude=1.0), day2)
    fifth = baseline.score(replace(candidate, magnitude=30.0), day3)

    assert first.history_n == second.history_n == 0
    assert third.history_n == fourth.history_n == 2
    assert third.status == "scored"
    assert third.thresholds_crossed == (0.5, 0.9)
    assert fifth.history_n == 4


def test_baseline_rejects_session_time_regression() -> None:
    before = state(1)
    after = state(2, bids=[(100.0, 10, 1), (70.0, 20, 1)])
    candidate = detect_candidates(before, after, instrument_id="NIFTY-FUT").candidates[0]
    baseline = PreviousSessionEmpiricalBaseline(minimum_history=1)
    baseline.score(candidate, BaselineContext("later", 2, "09:30", "L1", "R1"))

    with pytest.raises(ValueError, match="strictly increasing"):
        baseline.score(candidate, BaselineContext("earlier", 1, "09:30", "L1", "R1"))


def test_candidate_schema_is_outcome_blind() -> None:
    names = {
        item.name
        for item in fields(detect_candidates(state(1), state(2), instrument_id="X").__class__)
    }
    candidate_names = {
        item.name
        for item in fields(
            detect_candidates(
                state(1),
                state(2, bids=[(100.0, 10, 1), (70.0, 20, 1)]),
                instrument_id="X",
            ).candidates[0]
        )
    }

    forbidden = {"future", "return", "response", "label", "midpoint"}
    assert not (names & forbidden)
    assert not (candidate_names & forbidden)
