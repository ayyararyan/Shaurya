"""Regression cover for the primitives retained after `CCZ-IMPL-02` retired this scan.

The price-keyed cumulative construction that used to live here is gone.  `VAL-CCZ-02` asserts it
cannot come back; these tests pin the transition-validity, control and mid-return helpers that the
surviving CCZ and CKS scans share.
"""

from __future__ import annotations

from math import isclose

from shaurya.analytics.depth_thinning_analysis import DEPTH20, DEPTH200, BookState
from shaurya.signals.deep_book_normal_activity import build_depth20_mid_series
from shaurya.signals.deep_book_ofi import (
    CAUSAL_GAP_SECONDS,
    FUTURES_TICK_SIZE,
    OFI_WINDOWS_SECONDS,
    RETIRED_BY,
    RETIRED_EXPLORATORY_SCAN_ID,
    _controls,
    _invalid_transition,
    _label,
    _mid_return,
)


def _state(
    stamp: int,
    bids: tuple[tuple[float, int, int], ...],
    asks: tuple[tuple[float, int, int], ...],
    *,
    channel: str = DEPTH200,
    epoch: int = 0,
    quality_flags: tuple[str, ...] = (),
) -> BookState:
    return BookState(
        channel=channel,
        receive_ts_ns=stamp,
        receive_sequence=stamp,
        connection_epoch=epoch,
        bids=bids,
        asks=asks,
        rows_in_burst=1,
        quality_flags=quality_flags,
    )


def test_module_records_the_retirement_rather_than_pretending_it_never_existed() -> None:
    assert RETIRED_EXPLORATORY_SCAN_ID == "X-OFI-DAT20-03"
    assert RETIRED_BY == "D37 / CCZ-OFI-MIGRATION-2026-08-20"


def test_module_no_longer_exports_the_cumulative_construction() -> None:
    import shaurya.signals.deep_book_ofi as module

    assert not hasattr(module, "price_keyed_ofi_transition")
    assert not hasattr(module, "PriceKeyedOFITransition")
    assert not hasattr(module, "DEPTH_CUTOFFS")
    assert not hasattr(module, "build_ofi_artifact")


def test_connection_epoch_boundary_refuses_the_transition() -> None:
    previous = _state(1, ((100.0, 10, 1),), ((101.0, 10, 1),), epoch=0)
    current = _state(2, ((100.0, 12, 1),), ((101.0, 10, 1),), epoch=1)

    assert _invalid_transition(previous, current) == "connection_epoch_boundary"


def test_non_monotone_and_crossed_books_are_refused() -> None:
    previous = _state(5, ((100.0, 10, 1),), ((101.0, 10, 1),))
    backwards = _state(4, ((100.0, 10, 1),), ((101.0, 10, 1),))
    crossed = _state(6, ((102.0, 10, 1),), ((101.0, 10, 1),))

    assert _invalid_transition(previous, backwards) == "non_monotone_receive_time"
    assert _invalid_transition(previous, crossed) == "crossed_or_missing_book"
    assert _invalid_transition(previous, _state(6, (), ())) == "incomplete_two_sided_book"


def test_non_depth200_channel_is_refused() -> None:
    previous = _state(1, ((100.0, 10, 1),), ((101.0, 10, 1),), channel=DEPTH20)
    current = _state(2, ((100.0, 12, 1),), ((101.0, 10, 1),), channel=DEPTH20)

    assert _invalid_transition(previous, current) == "not_depth200"


def test_controls_report_spread_and_microprice_tilt_in_ticks() -> None:
    state = _state(1, ((100.0, 30, 1),), ((100.05, 10, 1),))

    controls = _controls(state)

    assert controls is not None
    assert isclose(controls["spread_ticks"], 1.0)
    # A heavier bid queue tilts the microprice towards the ask, so the tilt is positive.
    assert controls["microprice_tilt_ticks"] > 0.0


def test_mid_return_is_none_when_an_endpoint_is_unavailable() -> None:
    states = [
        _state(index * 1_000_000_000, ((100.0, 10, 1),), ((100.10, 10, 1),), channel=DEPTH20)
        for index in range(1, 4)
    ]
    series = build_depth20_mid_series(states)

    assert _mid_return(series, 0, 500) is None
    assert _mid_return(series, 3_000_000_000, 3_000_000_000) is None


def test_shared_constants_are_unchanged_by_the_migration() -> None:
    assert OFI_WINDOWS_SECONDS == (0.5, 1.0, 2.0, 5.0, 10.0)
    assert CAUSAL_GAP_SECONDS == 0.5
    assert FUTURES_TICK_SIZE == 0.05
    assert _label(0.5) == "0p5"
    assert _label(10.0) == "10"
