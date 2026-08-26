"""Shared book-transition primitives retained after the CCZ migration retired this scan.

`CCZ-IMPL-02`.  This module previously implemented the exploratory price-keyed OFI scan
`X-OFI-DAT20-03`: signed quantity innovations keyed by absolute price, accumulated into a
**running sum across levels** (``cumulative_by_depth[L] = sum over rank <= L``) and left
unnormalised.  Cont-Cucuringu-Zhang never cumulate across levels and always divide by a depth
scale, so that construction is not the CCZ multi-level OFI and has been removed under the frozen
migration `D37 / CCZ-OFI-MIGRATION-2026-08-20`.

The CCZ estimator lives in :mod:`shaurya.signals.ccz_ofi` and is now the single definition of
order flow imbalance in this repository.

What remains here are the transition-validity, control and mid-return helpers that the surviving
scans share; they were never part of the defective construction.  Already-published
`X-OFI-DAT20-03` artifacts are preserved and permanently relabelled as a non-CCZ construction;
they are neither deleted nor pooled with post-migration numbers.
"""

from __future__ import annotations

from shaurya.analytics.depth_thinning_analysis import DEPTH200, BookState
from shaurya.signals.deep_book_anomaly import INVALID_QUALITY_FLAGS
from shaurya.signals.deep_book_normal_activity import Depth20MidSeries

RETIRED_EXPLORATORY_SCAN_ID = "X-OFI-DAT20-03"
RETIRED_BY = "D37 / CCZ-OFI-MIGRATION-2026-08-20"
OFI_WINDOWS_SECONDS = (0.5, 1.0, 2.0, 5.0, 10.0)
CAUSAL_GAP_SECONDS = 0.5
FUTURES_TICK_SIZE = 0.05


def _label(value: float) -> str:
    return str(value).replace(".", "p").rstrip("0").rstrip("p")


def _invalid_transition(previous: BookState, current: BookState) -> str | None:
    """Refuse a transition that cannot carry an order-flow interpretation."""

    if previous.channel != DEPTH200 or current.channel != DEPTH200:
        return "not_depth200"
    if current.receive_ts_ns <= previous.receive_ts_ns:
        return "non_monotone_receive_time"
    if current.connection_epoch != previous.connection_epoch:
        return "connection_epoch_boundary"
    flags = (set(previous.quality_flags) | set(current.quality_flags)) & INVALID_QUALITY_FLAGS
    if flags:
        return "invalid_quality:" + ",".join(sorted(flags))
    if not previous.bids or not previous.asks or not current.bids or not current.asks:
        return "incomplete_two_sided_book"
    if (
        previous.best_bid is None
        or previous.best_ask is None
        or current.best_bid is None
        or current.best_ask is None
        or previous.best_bid >= previous.best_ask
        or current.best_bid >= current.best_ask
    ):
        return "crossed_or_missing_book"
    return None


def _controls(state: BookState) -> dict[str, float] | None:
    if not state.bids or not state.asks:
        return None
    bid, bid_quantity, _ = state.bids[0]
    ask, ask_quantity, _ = state.asks[0]
    if bid >= ask or bid_quantity + ask_quantity <= 0:
        return None
    midpoint = (bid + ask) / 2.0
    microprice = (ask_quantity * bid + bid_quantity * ask) / (bid_quantity + ask_quantity)
    return {
        "spread_ticks": (ask - bid) / FUTURES_TICK_SIZE,
        "microprice_tilt_ticks": (microprice - midpoint) / FUTURES_TICK_SIZE,
    }


def _mid_return(series: Depth20MidSeries, start_ts_ns: int, end_ts_ns: int) -> float | None:
    start = series.as_of(start_ts_ns)
    end = series.as_of(end_ts_ns)
    if start is None or end is None or end_ts_ns <= start_ts_ns:
        return None
    return (end - start) / FUTURES_TICK_SIZE
