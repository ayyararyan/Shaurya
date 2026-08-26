"""Exploratory scan `X-DEEPBOOK-DAT20-02` — what ordinary depth200 activity says about price.

**No anomalies.** This scan deliberately contains no threshold, no rare-tail selection, no
episode construction and no anomaly detector.  It looks at the ordinary state and flow of the
200-level NIFTY futures book at every depth200 publication and asks what, if anything, it says
about the next move in the depth20 mid-price.

Aryan directed it by voice on 2026-08-19: *"these were only based on abnormal events that happened
in 11 seconds. I want to know a basic question — what does normal order book activity tell us
about predictive power of the futures at 200 levels? ... Before we do that, let us see what does
normal limit order activity predict in prices."*

**This is not `H-SIG21` and must never be described as part of it.**  It shares the two source
tapes and the depth20 mid-price target convention, and nothing else: no registered family, no
registered thresholds, no registered strata, no verdict vocabulary.  `H-SIG21`'s 384-cell family
is untouched by anything here.

**It can never be confirmatory.**  Both `DAT-20` tapes were captured at 13:09 and 13:20 IST, about
an hour and fifty minutes before the `H-SIG21` registering commit `f2cf6501` was pushed at
15:00:42 IST.  They were already permanently outside any confirmatory sample.  Every artifact
carries ``confirmatory_eligible: false``; :func:`assert_exploratory_claim` refuses a confirmatory
or economic framing before a file is opened; :func:`assert_permitted_tape` refuses any tape whose
SHA-256 is not one of the two pinned pre-registration captures.

**The central question this module is built to answer** is not "does the book predict" but
"does anything beyond level 20 add predictive information once the near book is already accounted
for?".  That is :func:`nested_region_comparison`: best quote only, then top 5, then top 20, then
levels 21-50, then levels 51-200, each step measured out of sample across an embargoed split.

Working-contract §7.1 object categories: every region total, imbalance, average order size, shape
measure and difference is **deterministically derived** from the displayed book.  Every fit,
out-of-sample R², standard error, confidence interval and test statistic is **estimated**.  There
is no message stream in the feed, so per-order identity, per-order lifetime and true order flow
are **unidentified**; average order size (quantity ÷ order count) is the one genuine partial
recovery and is labelled a **proxy** for order granularity wherever it appears.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray
from shaurya.contracts.timing import NSE_EQUITY_DERIVATIVES_CURRENT_SESSION_SECONDS

from shaurya.analytics.depth_thinning_analysis import BookState, percentile
from shaurya.signals.deep_book_construction_grid import time_bucket_ist
from shaurya.signals.deep_book_response import (
    NANOSECONDS_PER_SECOND,
    depth20_midpoint,
)

EXPLORATORY_SCAN_ID = "X-DEEPBOOK-DAT20-02"
CONFIRMATORY_ELIGIBLE = False
SAMPLE_ROLE = "exploratory_scan_pre_registration_capture"

# This scan is NOT part of H-SIG21. It is recorded here only so the shared-tape justification can
# be stated exactly and so nobody has to reconstruct why looking at these price paths was allowed.
SIG21_REGISTERING_COMMIT = "f2cf65011d02882191b5cfda566c1024119964d7"
SIG21_REGISTERING_COMMIT_TIMESTAMP_IST = "2026-08-19T15:00:42+05:30"

# The only two tapes this scan may ever open, pinned by content hash. Both were captured before
# the H-SIG21 registering commit, which is exactly why their price paths can be looked at.
PERMITTED_TAPE_SHA256 = frozenset(
    {
        "751ee15ad5681bd356db06983c86c4aa6fabbcd26ccab356b7e80d77955b71e0",
        "c20590d66631ac3b63748ccbdf172f2e5e2fe81b61b618f3e5df542108c82b82",
    }
)

FUTURES_TICK_SIZE = 0.05

# Aryan asked for the decay to be visible, so the horizon set runs well past H-SIG21's 10 s.
HORIZONS_SECONDS: tuple[int, ...] = (1, 5, 10, 30, 60)

# Level-index regions. `H-SIG21`'s question is about what sits beyond the publicly visible top 20,
# so the nesting is built to isolate exactly that.
LEVEL_REGIONS: tuple[tuple[str, int, int], ...] = (
    ("best", 1, 1),
    ("l1_5", 1, 5),
    ("l1_20", 1, 20),
    ("l21_50", 21, 50),
    ("l51_200", 51, 200),
)

# Price-distance regions, in rupees from the same-side best quote. Level index and price distance
# are not the same thing on a book with irregular price gaps, so both parameterisations are
# reported and neither is presented as the definitive one.
DISTANCE_REGIONS: tuple[tuple[str, float, float], ...] = (
    ("d_le5", 0.0, 5.0),
    ("d_5_20", 5.0, 20.0),
    ("d_20_50", 20.0, 50.0),
    ("d_gt50", 50.0, float("inf")),
)

KNOWN_REGIONS: frozenset[str] = frozenset(
    {region for region, *_ in LEVEL_REGIONS} | {region for region, *_ in DISTANCE_REGIONS}
)

# Look-backs for the flow (change) features. `tick` is the change since the immediately preceding
# depth200 publication.
FLOW_LOOKBACKS: tuple[tuple[str, float | None], ...] = (
    ("tick", None),
    ("1s", 1.0),
    ("5s", 5.0),
)

# Nested model ladder for the central test. Each step adds one region's features to the previous
# step's, so the increment is exactly "what this region adds once the nearer book is accounted for".
NESTED_LADDER: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("best_quote_only", ("best",)),
    ("top_5", ("best", "l1_5")),
    ("top_20", ("best", "l1_5", "l1_20")),
    ("plus_21_50", ("best", "l1_5", "l1_20", "l21_50")),
    ("plus_51_200", ("best", "l1_5", "l1_20", "l21_50", "l51_200")),
)

DISTANCE_LADDER: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("within_5", ("d_le5",)),
    ("within_20", ("d_le5", "d_5_20")),
    ("within_50", ("d_le5", "d_5_20", "d_20_50")),
    ("beyond_50", ("d_le5", "d_5_20", "d_20_50", "d_gt50")),
)

# Chronological out-of-sample split. The embargo must exceed the longest target horizon, or a
# training observation's 60-second target window would still be open when the test set starts.
TRAIN_FRACTION = 0.70
EMBARGO_SECONDS = 120.0

# The first run of this scan selected the largest penalty in a grid ending at 1e3 for every rung
# at every horizon. A selection pinned to the edge of its own grid is a censored search, not a
# choice, so the grid was extended upward until the selection stopped hitting the boundary.
RIDGE_PENALTIES: tuple[float, ...] = (
    0.0,
    0.1,
    1.0,
    10.0,
    100.0,
    1_000.0,
    10_000.0,
    100_000.0,
    1_000_000.0,
    10_000_000.0,
)

BLOCK_BOOTSTRAP_REPLICATES = 399
BOOTSTRAP_SEED = 20260819
NORMAL_95_CRITICAL_VALUE = 1.959964

# Yardstick only (D11(c) / SIG-18 logic): a deliberately flexible model whose only job is to bound
# how much predictable structure exists in principle. Never a strategy candidate.
YARDSTICK_ROUNDS = 200
YARDSTICK_LEARNING_RATE = 0.05
YARDSTICK_SPLIT_CANDIDATES = 24

MINIMUM_FIT_OBSERVATIONS = 30
MINIMUM_BLOCK_OBSERVATIONS = 8

ObjectCategory = Literal[
    "observed",
    "deterministically_derived",
    "estimated",
    "scenario_based",
    "proxy",
    "unidentified",
]

# A claim naming any of these is a confirmatory or economic claim, which this scan is not
# authorised to make. Whole-word matching, so "unconfirmed" and "falsifiable" are not caught.
FORBIDDEN_CLAIM_TOKENS = frozenset(
    {
        "admissible",
        "alpha",
        "confirmatory",
        "confirmed",
        "edge",
        "falsified",
        "informative",
        "predictive",
        "profitable",
        "promote",
        "promotion",
        "signal",
        "tradable",
        "tradeable",
        "verdict",
    }
)


class ConfirmatoryUseRefused(RuntimeError):
    """Raised when this exploratory scan is asked to behave as a confirmatory test."""


class TapeNotPermitted(RuntimeError):
    """Raised when a tape outside the two pre-registration DAT-20 captures is offered."""


class IncompleteTableRefused(RuntimeError):
    """Raised when a table is about to be emitted filtered to its interesting rows."""


def claim_tokens(name: str) -> frozenset[str]:
    """Split an identifier or phrase into lowercase word tokens for whole-word matching."""

    return frozenset(part for part in re.split(r"[^a-z0-9]+", str(name).strip().lower()) if part)


def assert_exploratory_claim(claims: Iterable[str]) -> None:
    """Refuse any request to dress this scan up as a confirmatory or economic result."""

    offending = sorted({name for name in claims if claim_tokens(name) & FORBIDDEN_CLAIM_TOKENS})
    if offending:
        raise ConfirmatoryUseRefused(
            f"{EXPLORATORY_SCAN_ID} is an exploratory scan with "
            f"confirmatory_eligible={CONFIRMATORY_ELIGIBLE}. Its two tapes were captured before "
            f"the H-SIG21 registering commit {SIG21_REGISTERING_COMMIT[:8]} was pushed at "
            f"{SIG21_REGISTERING_COMMIT_TIMESTAMP_IST}, so they sit permanently outside any "
            "confirmatory sample; and 22 minutes of one contract in one direction cannot support "
            f"an economic claim in any case. Refused claim(s): {', '.join(offending)}."
        )


def assert_permitted_tape(*, run_id: str, tape_sha256: str) -> None:
    """Refuse any tape that is not one of the two pre-registration DAT-20 captures."""

    if tape_sha256 not in PERMITTED_TAPE_SHA256:
        raise TapeNotPermitted(
            f"{EXPLORATORY_SCAN_ID} may only open the two DAT-20 tapes captured before the "
            f"H-SIG21 registering commit. Tape {run_id!r} has SHA-256 {tape_sha256}, which is not "
            "one of them. Feeding a post-registration capture to this scan would inspect a price "
            "path that H-SIG21 §1.5 reserves for its first outcome sample."
        )


def assert_complete_table(*, emitted: int, expected: int, name: str) -> None:
    """Refuse a table that has been filtered, ranked-and-truncated or sampled."""

    if emitted != expected:
        raise IncompleteTableRefused(
            f"{name} must be emitted complete: expected {expected} rows, got {emitted}. "
            "Reporting only the interesting rows of a search is how a 22-minute tape becomes a "
            "false result."
        )


# ----------------------------------------------------------------------------------------------
# Ordinary book state — one feature vector per depth200 publication
# ----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RegionTotals:
    """Displayed quantity, order count and average order size for one side of one region."""

    quantity: float
    order_count: float
    occupied_levels: int

    @property
    def average_order_size(self) -> float | None:
        """Quantity per displayed order.

        **Proxy.** The feed carries no order IDs, so individual order sizes are unidentified.
        This ratio is the one genuine partial recovery of order granularity available: it says
        whether a region's displayed size is a few large orders or many small ones.
        """

        return self.quantity / self.order_count if self.order_count > 0 else None


def _levels_in_index_range(
    ladder: Sequence[tuple[float, int, int]], first: int, last: int
) -> tuple[tuple[float, int, int], ...]:
    return tuple(ladder[first - 1 : last])


def _levels_in_distance_range(
    ladder: Sequence[tuple[float, int, int]],
    *,
    best_price: float,
    low: float,
    high: float,
) -> tuple[tuple[float, int, int], ...]:
    """Levels whose distance from the same-side best quote is in ``[low, high)`` rupees."""

    selected = []
    for price, quantity, orders in ladder:
        distance = abs(price - best_price)
        if low <= distance < high:
            selected.append((price, quantity, orders))
    return tuple(selected)


def _totals(levels: Sequence[tuple[float, int, int]]) -> RegionTotals:
    return RegionTotals(
        quantity=float(sum(level[1] for level in levels)),
        order_count=float(sum(level[2] for level in levels)),
        occupied_levels=len(levels),
    )


def _imbalance(bid: float, ask: float) -> float | None:
    total = bid + ask
    return (bid - ask) / total if total > 0 else None


def _depth_weighted_offset(
    levels: Sequence[tuple[float, int, int]], *, midpoint: float
) -> float | None:
    """Quantity-weighted mean distance of displayed size from the mid-price, in rupees.

    Large when the side's displayed size sits far from the mid, small when it is concentrated at
    the touch.  Reported per side, so the two together describe the book's shape rather than its
    level.
    """

    total = sum(level[1] for level in levels)
    if total <= 0:
        return None
    return sum(abs(level[0] - midpoint) * level[1] for level in levels) / total


def _size_build_slope(
    levels: Sequence[tuple[float, int, int]], *, best_price: float
) -> float | None:
    """How steeply displayed size builds with distance from the touch, per side.

    Ordinary least squares slope of level quantity on distance-from-best-quote in rupees, over the
    occupied levels of the side.  Positive means the book gets heavier as it goes deeper.  It is a
    shape descriptor, not a fitted model of anything.
    """

    if len(levels) < 3:
        return None
    distances = [abs(level[0] - best_price) for level in levels]
    quantities = [float(level[1]) for level in levels]
    n = len(distances)
    mean_x = sum(distances) / n
    mean_y = sum(quantities) / n
    sxx = sum((value - mean_x) ** 2 for value in distances)
    if sxx <= 0:
        return None
    sxy = sum(
        (x - mean_x) * (y - mean_y) for x, y in zip(distances, quantities, strict=True)
    )
    return sxy / sxx


def book_state_features(state: BookState) -> dict[str, float] | None:
    """Every ordinary-state feature of one depth200 publication.

    Returns ``None`` when the state cannot supply a usable two-sided book — an empty side, a
    crossed book or a missing best quote.  Nothing is imputed and no missing value is silently
    treated as zero.
    """

    bids, asks = state.bids, state.asks
    if not bids or not asks:
        return None
    best_bid, best_ask = bids[0][0], asks[0][0]
    if not (isfinite(best_bid) and isfinite(best_ask)) or best_bid >= best_ask:
        return None
    midpoint = (best_bid + best_ask) / 2.0
    # The spread is a best-quote object and is named into the `best` region deliberately. If it
    # were region-free it would sit in every rung of the nested ladder, which is correct, but
    # naming it explicitly is what makes that visible rather than accidental.
    features: dict[str, float] = {
        "best__spread_rupees": best_ask - best_bid,
        "midpoint": midpoint,
    }

    regions: list[tuple[str, Sequence[tuple[float, int, int]], Sequence[tuple[float, int, int]]]]
    regions = []
    for name, first, last in LEVEL_REGIONS:
        regions.append(
            (
                name,
                _levels_in_index_range(bids, first, last),
                _levels_in_index_range(asks, first, last),
            )
        )
    for name, low, high in DISTANCE_REGIONS:
        regions.append(
            (
                name,
                _levels_in_distance_range(bids, best_price=best_bid, low=low, high=high),
                _levels_in_distance_range(asks, best_price=best_ask, low=low, high=high),
            )
        )

    for name, bid_levels, ask_levels in regions:
        bid_totals, ask_totals = _totals(bid_levels), _totals(ask_levels)
        features[f"{name}__bid_quantity"] = bid_totals.quantity
        features[f"{name}__ask_quantity"] = ask_totals.quantity
        features[f"{name}__bid_order_count"] = bid_totals.order_count
        features[f"{name}__ask_order_count"] = ask_totals.order_count
        features[f"{name}__bid_occupied_levels"] = float(bid_totals.occupied_levels)
        features[f"{name}__ask_occupied_levels"] = float(ask_totals.occupied_levels)
        quantity_imbalance = _imbalance(bid_totals.quantity, ask_totals.quantity)
        count_imbalance = _imbalance(bid_totals.order_count, ask_totals.order_count)
        features[f"{name}__quantity_imbalance"] = (
            quantity_imbalance if quantity_imbalance is not None else 0.0
        )
        features[f"{name}__order_count_imbalance"] = (
            count_imbalance if count_imbalance is not None else 0.0
        )
        # Average order size is a proxy for order granularity; zero displayed orders means the
        # region is empty, and an empty region's average size is reported as 0.0 rather than
        # imputed, with the occupied-level count carried alongside so emptiness stays visible.
        bid_average = bid_totals.average_order_size
        ask_average = ask_totals.average_order_size
        features[f"{name}__bid_average_order_size_proxy"] = (
            bid_average if bid_average is not None else 0.0
        )
        features[f"{name}__ask_average_order_size_proxy"] = (
            ask_average if ask_average is not None else 0.0
        )
        average_imbalance = _imbalance(
            bid_average if bid_average is not None else 0.0,
            ask_average if ask_average is not None else 0.0,
        )
        features[f"{name}__average_order_size_imbalance_proxy"] = (
            average_imbalance if average_imbalance is not None else 0.0
        )

    # Book shape is computed **per region**, never once over the whole 200-level ladder. A single
    # whole-book shape number would consume levels 51-200 and then sit in the `best_quote_only`
    # rung of the nested ladder, which would leak exactly the information the central test is
    # trying to measure. Region-scoped shape nests correctly.
    for name, bid_levels, ask_levels in regions:
        for side, levels, best_price in (
            ("bid", bid_levels, best_bid),
            ("ask", ask_levels, best_ask),
        ):
            offset = _depth_weighted_offset(levels, midpoint=midpoint)
            features[f"{name}__{side}_depth_weighted_offset_rupees"] = (
                offset if offset is not None else 0.0
            )
            slope = _size_build_slope(levels, best_price=best_price)
            features[f"{name}__{side}_size_build_slope"] = slope if slope is not None else 0.0
        offset_imbalance = _imbalance(
            features[f"{name}__bid_depth_weighted_offset_rupees"],
            features[f"{name}__ask_depth_weighted_offset_rupees"],
        )
        features[f"{name}__depth_weighted_offset_imbalance"] = (
            offset_imbalance if offset_imbalance is not None else 0.0
        )
    return features


# Features that are book *levels* rather than book *positions*: differencing them is meaningful and
# they are the ones the flow block operates on. `midpoint` is excluded because differencing it
# would hand the model the price itself.
def _flow_eligible(name: str) -> bool:
    return name != "midpoint"


@dataclass(frozen=True, slots=True)
class Observation:
    """One depth200 publication with its ordinary features and its future/past responses."""

    tape_index: int
    run_id: str
    receive_ts_ns: int
    time_bucket: str
    features: Mapping[str, float]
    future_ticks: Mapping[float, float]
    past_ticks: Mapping[float, float]
    contemporaneous_ticks: Mapping[float, float]


def build_flow_features(
    states: Sequence[BookState],
    level_features: Sequence[Mapping[str, float]],
) -> list[dict[str, float]]:
    """Short-window changes in every level feature, per publication.

    Three look-backs: the change since the immediately preceding publication, and the change over
    1-second and 5-second look-backs resolved as-of (the last publication at or before the
    look-back instant, never interpolated forward).  A publication with no usable earlier
    reference for a given look-back gets a change of zero for that look-back and a companion
    ``__available`` flag of zero, so an unavailable difference is never mistaken for a measured
    zero.
    """

    if len(states) != len(level_features):
        raise ValueError("states and level features must be aligned")
    timestamps = [state.receive_ts_ns for state in states]
    names = sorted(name for name in level_features[0] if _flow_eligible(name)) if states else []
    flows: list[dict[str, float]] = []
    for position, stamp in enumerate(timestamps):
        current = level_features[position]
        row: dict[str, float] = {}
        for label, lookback in FLOW_LOOKBACKS:
            if lookback is None:
                reference = position - 1 if position > 0 else None
            else:
                target = stamp - int(round(lookback * NANOSECONDS_PER_SECOND))
                candidate = bisect_right(timestamps, target) - 1
                reference = candidate if candidate >= 0 and candidate != position else None
            available = reference is not None
            row[f"flow_{label}__available"] = 1.0 if available else 0.0
            previous = level_features[reference] if reference is not None else None
            for name in names:
                row[f"flow_{label}__{name}"] = (
                    current[name] - previous[name] if previous is not None else 0.0
                )
        flows.append(row)
    return flows


# ----------------------------------------------------------------------------------------------
# Target — the depth20 mid-price move, forward, backward and contemporaneous
# ----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Depth20MidSeries:
    """The depth20 mid-price path, with the as-of and coverage rules applied once."""

    timestamps: tuple[int, ...]
    midpoints: tuple[float, ...]

    @property
    def coverage_start_ts_ns(self) -> int | None:
        return self.timestamps[0] if self.timestamps else None

    @property
    def coverage_end_ts_ns(self) -> int | None:
        return self.timestamps[-1] if self.timestamps else None

    def as_of(self, target_ts_ns: int) -> float | None:
        """The last mid-price at or before ``target_ts_ns``. Never interpolates forward.

        Refuses any target outside the covered span.  At the right edge of a finite tape the as-of
        rule alone is unsafe: an endpoint past the final observation silently resolves back to it
        and fabricates a measurement.  That defect was found on these exact tapes and is recorded
        in `research/docs/SIG-21-EXPLORATORY-RESPONSE-2026-08-19.md` §6.1.
        """

        if not self.timestamps:
            return None
        if target_ts_ns < self.timestamps[0] or target_ts_ns > self.timestamps[-1]:
            return None
        position = bisect_right(self.timestamps, target_ts_ns) - 1
        return self.midpoints[position] if position >= 0 else None


def build_depth20_mid_series(states: Sequence[BookState]) -> Depth20MidSeries:
    """Collapse depth20 states into the usable mid-price path, dropping unusable states."""

    timestamps: list[int] = []
    midpoints: list[float] = []
    for state in states:
        midpoint = depth20_midpoint(state)
        if midpoint is None:
            continue
        if timestamps and state.receive_ts_ns <= timestamps[-1]:
            continue
        timestamps.append(state.receive_ts_ns)
        midpoints.append(float(midpoint))
    return Depth20MidSeries(tuple(timestamps), tuple(midpoints))


def response_ticks(
    series: Depth20MidSeries,
    *,
    anchor_ts_ns: int,
    horizons_seconds: Sequence[int] = HORIZONS_SECONDS,
    tick_size: float = FUTURES_TICK_SIZE,
) -> tuple[dict[float, float], dict[float, float], dict[float, float]]:
    """Future, past-mirror and contemporaneous mid-price moves at one publication instant.

    - **future** — the move from the anchor to ``anchor + h``.  This is the thing being predicted.
    - **past mirror** — the move from ``anchor - h`` to the anchor, over the same span.  This is a
      negative control: a feature that predicts the past as strongly as the future is measuring
      drift, not information.
    - **contemporaneous** — the move across the depth20 publication interval that *straddles* the
      anchor: from the last mid strictly before the depth200 publication to the first mid at or
      after it.  It is what the price is doing *while* the book state is observed.  It uses
      information from after the anchor, deliberately, because its only job is to expose a feature
      that is reacting rather than leading.  It is reported separately and is never merged into
      the future move, never a target the model is scored on, and never a predictor.

      **This was wrong in the first run of this scan.** It was defined as "the last mid before the
      anchor to the mid *at* the anchor", but the as-of rule resolves both to the same publication
      when the anchor does not coincide with a depth20 timestamp — which it never does, because
      the two channels publish on different clocks. Every contemporaneous value was therefore
      identically 0.0 and the diagnostic could not have fired whatever the data did.
    """

    anchor = series.as_of(anchor_ts_ns)
    future: dict[float, float] = {}
    past: dict[float, float] = {}
    contemporaneous: dict[float, float] = {}
    if anchor is None:
        return future, past, contemporaneous
    for horizon in horizons_seconds:
        offset = horizon * NANOSECONDS_PER_SECOND
        ahead = series.as_of(anchor_ts_ns + offset)
        if ahead is not None:
            future[horizon] = (ahead - anchor) / tick_size
        behind = series.as_of(anchor_ts_ns - offset)
        if behind is not None:
            past[horizon] = (anchor - behind) / tick_size
    before = bisect_left(series.timestamps, anchor_ts_ns) - 1
    at_or_after = bisect_left(series.timestamps, anchor_ts_ns)
    if before >= 0 and at_or_after < len(series.timestamps):
        straddle = (
            series.midpoints[at_or_after] - series.midpoints[before]
        ) / tick_size
        for horizon in horizons_seconds:
            contemporaneous[horizon] = straddle
    return future, past, contemporaneous


def build_observations(
    *,
    depth200_states: Sequence[BookState],
    depth20_states: Sequence[BookState],
    tape_index: int,
    run_id: str,
    horizons_seconds: Sequence[int] = HORIZONS_SECONDS,
) -> tuple[list[Observation], dict[str, int]]:
    """One observation per usable depth200 publication, with every drop reason counted."""

    series = build_depth20_mid_series(depth20_states)
    usable_states: list[BookState] = []
    usable_features: list[dict[str, float]] = []
    failures: dict[str, int] = {
        "unusable_depth200_state": 0,
        "no_depth20_anchor": 0,
        "no_future_horizon_covered": 0,
    }
    for state in depth200_states:
        features = book_state_features(state)
        if features is None:
            failures["unusable_depth200_state"] += 1
            continue
        usable_states.append(state)
        usable_features.append(features)
    flows = build_flow_features(usable_states, usable_features)
    observations: list[Observation] = []
    for state, level, flow in zip(usable_states, usable_features, flows, strict=True):
        if series.as_of(state.receive_ts_ns) is None:
            failures["no_depth20_anchor"] += 1
            continue
        future, past, contemporaneous = response_ticks(
            series, anchor_ts_ns=state.receive_ts_ns, horizons_seconds=horizons_seconds
        )
        if not future:
            failures["no_future_horizon_covered"] += 1
            continue
        merged = dict(level)
        merged.update(flow)
        observations.append(
            Observation(
                tape_index=tape_index,
                run_id=run_id,
                receive_ts_ns=state.receive_ts_ns,
                time_bucket=time_bucket_ist(state.receive_ts_ns),
                features=merged,
                future_ticks=future,
                past_ticks=past,
                contemporaneous_ticks=contemporaneous,
            )
        )
    return observations, failures


# ----------------------------------------------------------------------------------------------
# Feature naming — which region does a feature belong to
# ----------------------------------------------------------------------------------------------


def feature_region(name: str) -> str | None:
    """The region a feature belongs to, or ``None`` for a region-free feature.

    Region membership drives the whole nested comparison, so it is derived from the name once,
    here, rather than reconstructed at each call site where it could drift.
    """

    body = name
    if name.startswith("flow_"):
        # `flow_<lookback>__<level feature name>`; strip exactly one leading segment.
        body = name.split("__", 1)[1] if "__" in name else ""
    head = body.split("__", 1)[0]
    return head if head in KNOWN_REGIONS else None


def features_for_regions(names: Sequence[str], regions: Sequence[str]) -> list[str]:
    """The feature names belonging to the given regions, plus every region-free feature.

    Region-free features — spread and the two book-shape descriptors — are in **every** rung of
    the ladder.  If they were only in the later rungs, the increment attributed to the deep book
    would silently include them and the central test would be answering a different question.
    """

    allowed = set(regions)
    selected = [
        name
        for name in names
        if (region := feature_region(name)) is None or region in allowed
    ]
    return sorted(set(selected) - {"midpoint"})


# ----------------------------------------------------------------------------------------------
# Out-of-sample design — chronological split with an embargo gap
# ----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SplitIndex:
    """A chronological train/test split with an embargoed gap, and what it discarded."""

    train: tuple[int, ...]
    test: tuple[int, ...]
    embargoed: tuple[int, ...]
    embargo_seconds: float
    boundaries: tuple[tuple[str, int, int], ...]


def chronological_embargoed_split(
    observations: Sequence[Observation],
    *,
    train_fraction: float = TRAIN_FRACTION,
    embargo_seconds: float = EMBARGO_SECONDS,
) -> SplitIndex:
    """Split each tape chronologically, discarding an embargo band at the internal boundary.

    The embargo exists because the target windows overlap: a training observation taken shortly
    before the split still has a 60-second window open across it, so without a gap the training
    target and the first test observations would share price path.  Every observation inside the
    band is **discarded from both sides**, not reassigned.

    Each tape is split separately and the parts pooled, so both tapes contribute to train and to
    test.  Splitting the pool once would put an entire tape on one side of the boundary and
    confound the split with the four-minute recording gap between the captures.
    """

    if not 0.0 < train_fraction < 1.0:
        raise ValueError("train_fraction must lie strictly between zero and one")
    if embargo_seconds < 0:
        raise ValueError("embargo_seconds must be non-negative")
    if embargo_seconds < float(max(HORIZONS_SECONDS)):
        raise ValueError(
            "embargo_seconds must be at least the longest target horizon, or a training "
            "observation's target window would still be open when the test set begins"
        )
    by_tape: dict[int, list[int]] = {}
    for position, observation in enumerate(observations):
        by_tape.setdefault(observation.tape_index, []).append(position)
    train: list[int] = []
    test: list[int] = []
    embargoed: list[int] = []
    boundaries: list[tuple[str, int, int]] = []
    embargo_ns = int(round(embargo_seconds * NANOSECONDS_PER_SECOND))
    for tape_index in sorted(by_tape):
        positions = sorted(by_tape[tape_index], key=lambda item: observations[item].receive_ts_ns)
        if len(positions) < 2:
            train.extend(positions)
            continue
        cut = max(1, int(len(positions) * train_fraction))
        boundary_ts = observations[positions[cut - 1]].receive_ts_ns
        boundaries.append((str(tape_index), boundary_ts, boundary_ts + embargo_ns))
        for position in positions:
            stamp = observations[position].receive_ts_ns
            if stamp <= boundary_ts:
                train.append(position)
            elif stamp <= boundary_ts + embargo_ns:
                embargoed.append(position)
            else:
                test.append(position)
    return SplitIndex(
        train=tuple(sorted(train)),
        test=tuple(sorted(test)),
        embargoed=tuple(sorted(embargoed)),
        embargo_seconds=embargo_seconds,
        boundaries=tuple(boundaries),
    )


# ----------------------------------------------------------------------------------------------
# Estimation — plain and regularised linear fits, standardised on the training set only
# ----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RidgeFit:
    """A ridge fit and the training-set standardisation it was estimated under."""

    feature_names: tuple[str, ...]
    coefficients: NDArray[np.float64]
    intercept: float
    centre: NDArray[np.float64]
    scale: NDArray[np.float64]
    penalty: float

    def predict(self, design: NDArray[np.float64]) -> NDArray[np.float64]:
        standardised = (design - self.centre) / self.scale
        return np.asarray(standardised @ self.coefficients + self.intercept, dtype=np.float64)


def _standardisation(
    design: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    centre = np.asarray(design.mean(axis=0), dtype=np.float64)
    scale = np.asarray(design.std(axis=0), dtype=np.float64)
    # A constant training column carries no information; scaling it by one leaves it at exactly
    # zero after centring, so it contributes nothing rather than producing a division by zero.
    scale[scale <= 0.0] = 1.0
    return centre, scale


def fit_ridge(
    design: NDArray[np.float64],
    target: NDArray[np.float64],
    *,
    feature_names: Sequence[str],
    penalty: float,
) -> RidgeFit:
    """Ridge regression with the intercept left unpenalised, standardised on this design only.

    ``penalty = 0`` is ordinary least squares, solved through the same least-squares routine, so
    the plain and regularised fits differ only in the penalty and never in the code path.
    """

    if design.ndim != 2 or design.shape[0] != target.shape[0]:
        raise ValueError("design and target must be aligned two-dimensional/one-dimensional")
    if design.shape[1] != len(feature_names):
        raise ValueError("design columns and feature names must agree")
    if penalty < 0:
        raise ValueError("penalty must be non-negative")
    return fit_ridge_path(
        design, target, feature_names=feature_names, penalties=(penalty,)
    )[penalty]


def fit_ridge_path(
    design: NDArray[np.float64],
    target: NDArray[np.float64],
    *,
    feature_names: Sequence[str],
    penalties: Sequence[float],
) -> dict[float, RidgeFit]:
    """Ridge fits at several penalties from one singular value decomposition.

    Every penalty on the same design shares the same decomposition, so a six-point penalty search
    costs one factorisation rather than six.  This is an engineering choice with no effect on the
    estimates: the returned coefficients are the exact ridge solutions.
    """

    centre, scale = _standardisation(design)
    standardised = (design - centre) / scale
    intercept = float(target.mean())
    centred_target = target - intercept
    left, singular, right_transposed = np.linalg.svd(standardised, full_matrices=False)
    projected = left.T @ centred_target
    fits: dict[float, RidgeFit] = {}
    for penalty in penalties:
        if penalty < 0:
            raise ValueError("penalty must be non-negative")
        denominator = singular**2 + penalty
        filtered = np.where(denominator > 0, singular * projected / denominator, 0.0)
        coefficients = right_transposed.T @ filtered
        fits[float(penalty)] = RidgeFit(
            feature_names=tuple(feature_names),
            coefficients=np.asarray(coefficients, dtype=np.float64),
            intercept=intercept,
            centre=centre,
            scale=scale,
            penalty=float(penalty),
        )
    return fits


def _design_matrix(
    observations: Sequence[Observation],
    positions: Sequence[int],
    feature_names: Sequence[str],
) -> NDArray[np.float64]:
    return np.asarray(
        [
            [observations[position].features.get(name, 0.0) for name in feature_names]
            for position in positions
        ],
        dtype=np.float64,
    ).reshape(len(positions), len(feature_names))


def _target_vector(
    observations: Sequence[Observation],
    positions: Sequence[int],
    *,
    horizon: int,
    source: Literal["future", "past", "contemporaneous"],
) -> NDArray[np.float64]:
    values = []
    for position in positions:
        observation = observations[position]
        table = {
            "future": observation.future_ticks,
            "past": observation.past_ticks,
            "contemporaneous": observation.contemporaneous_ticks,
        }[source]
        values.append(table[horizon])
    return np.asarray(values, dtype=np.float64)


def _covered(
    observations: Sequence[Observation],
    positions: Sequence[int],
    *,
    horizon: int,
    source: Literal["future", "past", "contemporaneous"],
) -> tuple[int, ...]:
    table_name = {
        "future": "future_ticks",
        "past": "past_ticks",
        "contemporaneous": "contemporaneous_ticks",
    }[source]
    return tuple(
        position
        for position in positions
        if horizon in getattr(observations[position], table_name)
    )


# ----------------------------------------------------------------------------------------------
# Dependence-aware inference on a heavily overlapping loss differential
# ----------------------------------------------------------------------------------------------


def _bartlett_long_run_variance(values: Sequence[float], *, lag: int) -> float:
    n = len(values)
    if n == 0:
        return 0.0
    mean = sum(values) / n
    residuals = [value - mean for value in values]
    total = sum(value * value for value in residuals) / n
    effective = min(lag, n - 1)
    for offset in range(1, effective + 1):
        covariance = (
            sum(residuals[index] * residuals[index - offset] for index in range(offset, n)) / n
        )
        total += 2.0 * (1.0 - offset / (lag + 1.0)) * covariance
    return max(total, 0.0)


@dataclass(frozen=True, slots=True)
class MeanEstimate:
    """A sample mean with three separately reported precisions.

    ``newey_west`` corrects the overlap in place; ``block_bootstrap`` resamples contiguous blocks
    within a tape; ``non_overlapping_block`` throws the overlap away by averaging inside disjoint
    blocks first.  They are reported side by side because on 22 minutes of tape they disagree, and
    which of them a reader trusts should be a visible choice rather than a hidden one.
    """

    n: int
    mean: float | None
    naive_standard_error: float | None
    newey_west_standard_error: float | None
    newey_west_t: float | None
    newey_west_lag: int
    block_bootstrap_standard_error: float | None
    block_bootstrap_t: float | None
    non_overlapping_blocks: int
    non_overlapping_mean: float | None
    non_overlapping_standard_error: float | None
    non_overlapping_t: float | None


def _block_means(
    values: Sequence[float], timestamps: Sequence[int], tapes: Sequence[int], *, block_ns: int
) -> list[float]:
    """Average within disjoint fixed-length time blocks, never spanning two tapes."""

    buckets: dict[tuple[int, int], list[float]] = {}
    origin: dict[int, int] = {}
    for value, stamp, tape in zip(values, timestamps, tapes, strict=True):
        origin.setdefault(tape, stamp)
        key = (tape, (stamp - origin[tape]) // block_ns)
        buckets.setdefault(key, []).append(value)
    return [sum(group) / len(group) for _, group in sorted(buckets.items())]


def _stationary_block_bootstrap_means(
    values: Sequence[float],
    tapes: Sequence[int],
    *,
    replicates: int,
    mean_block_length: float,
    seed: int,
) -> list[float]:
    """Stationary block bootstrap resampled within tape, so no replicate splices two captures."""

    grouped: dict[int, list[float]] = {}
    for value, tape in zip(values, tapes, strict=True):
        grouped.setdefault(tape, []).append(value)
    generator = np.random.default_rng(seed)
    restart = 1.0 / max(mean_block_length, 1.0)
    means: list[float] = []
    for _ in range(replicates):
        sample: list[float] = []
        for _, series in sorted(grouped.items()):
            size = len(series)
            index = int(generator.integers(size))
            for position in range(size):
                if position and generator.random() < restart:
                    index = int(generator.integers(size))
                elif position:
                    index = (index + 1) % size
                sample.append(series[index])
        means.append(sum(sample) / len(sample) if sample else 0.0)
    return means


def estimate_mean(
    values: Sequence[float],
    timestamps: Sequence[int],
    tapes: Sequence[int],
    *,
    overlap_seconds: float,
    replicates: int = BLOCK_BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> MeanEstimate:
    """Estimate a mean three ways under heavy window overlap, reporting all three."""

    n = len(values)
    if n == 0:
        return MeanEstimate(0, None, None, None, None, 0, None, None, 0, None, None, None)
    mean = sum(values) / n
    naive_variance = sum((value - mean) ** 2 for value in values) / n
    naive_se = sqrt(naive_variance / n) if n > 0 else None
    # HAC lag in observations: how many publications a single overlapping window can contain.
    lag = 1
    if overlap_seconds > 0 and n > 1:
        ordered = sorted(timestamps)
        span_ns = int(round(overlap_seconds * NANOSECONDS_PER_SECOND))
        for position, stamp in enumerate(ordered):
            lag = max(lag, bisect_right(ordered, stamp + span_ns) - position)
        lag = min(lag, max(1, n - 1))
    hac_se = sqrt(_bartlett_long_run_variance(values, lag=lag) / n)
    block_ns = max(1, int(round(overlap_seconds * NANOSECONDS_PER_SECOND)))
    blocks = _block_means(values, timestamps, tapes, block_ns=block_ns)
    block_mean: float | None = None
    block_se: float | None = None
    block_t: float | None = None
    if len(blocks) >= 2:
        block_mean = sum(blocks) / len(blocks)
        block_variance = sum((value - block_mean) ** 2 for value in blocks) / (len(blocks) - 1)
        block_se = sqrt(block_variance / len(blocks))
        block_t = block_mean / block_se if block_se > 0 else None
    bootstrap_se: float | None = None
    bootstrap_t: float | None = None
    if n >= MINIMUM_BLOCK_OBSERVATIONS:
        draws = _stationary_block_bootstrap_means(
            values,
            tapes,
            replicates=replicates,
            mean_block_length=float(max(1, lag)),
            seed=seed,
        )
        draw_mean = sum(draws) / len(draws)
        bootstrap_variance = sum((value - draw_mean) ** 2 for value in draws) / (len(draws) - 1)
        bootstrap_se = sqrt(bootstrap_variance)
        bootstrap_t = mean / bootstrap_se if bootstrap_se > 0 else None
    return MeanEstimate(
        n=n,
        mean=mean,
        naive_standard_error=naive_se,
        newey_west_standard_error=hac_se if hac_se > 0 else None,
        newey_west_t=(mean / hac_se) if hac_se > 0 else None,
        newey_west_lag=lag,
        block_bootstrap_standard_error=bootstrap_se,
        block_bootstrap_t=bootstrap_t,
        non_overlapping_blocks=len(blocks),
        non_overlapping_mean=block_mean,
        non_overlapping_standard_error=block_se,
        non_overlapping_t=block_t,
    )


# ----------------------------------------------------------------------------------------------
# THE CENTRAL TEST — does anything beyond level 20 add anything once the near book is accounted for
# ----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RungResult:
    """One rung of the nested ladder: fit on train, scored out of sample on test."""

    rung: str
    regions: tuple[str, ...]
    feature_count: int
    penalty: float
    train_n: int
    test_n: int
    out_of_sample_r2_vs_training_mean: float | None
    out_of_sample_r2_vs_zero: float | None
    in_sample_r2: float | None
    squared_errors: tuple[float, ...]


def _r_squared(
    actual: NDArray[np.float64],
    predicted: NDArray[np.float64],
    benchmark: NDArray[np.float64],
) -> float | None:
    residual = float(np.sum((actual - predicted) ** 2))
    baseline = float(np.sum((actual - benchmark) ** 2))
    return None if baseline <= 0 else 1.0 - residual / baseline


def _select_penalty(
    design: NDArray[np.float64],
    target: NDArray[np.float64],
    *,
    feature_names: Sequence[str],
    penalties: Sequence[float] = RIDGE_PENALTIES,
) -> float:
    """Choose the ridge penalty on a held-out *tail of the training set only*.

    The test set is never touched by penalty selection.  Using it would make the reported
    out-of-sample number an in-sample number wearing a disguise, which is the single easiest way
    to manufacture a result on a short tape.
    """

    n = design.shape[0]
    inner_cut = max(MINIMUM_FIT_OBSERVATIONS, int(n * 0.8))
    if n - inner_cut < MINIMUM_FIT_OBSERVATIONS:
        return float(penalties[len(penalties) // 2])
    inner_train, inner_validate = slice(0, inner_cut), slice(inner_cut, n)
    fits = fit_ridge_path(
        design[inner_train],
        target[inner_train],
        feature_names=feature_names,
        penalties=penalties,
    )
    best_penalty = float(penalties[0])
    best_error = float("inf")
    for penalty, fit in fits.items():
        error = float(
            np.mean((target[inner_validate] - fit.predict(design[inner_validate])) ** 2)
        )
        if error < best_error:
            best_error, best_penalty = error, float(penalty)
    return best_penalty


def _drift_adjust(
    train_target: NDArray[np.float64], test_target: NDArray[np.float64], *, adjust: bool
) -> tuple[NDArray[np.float64], NDArray[np.float64], float]:
    """Remove the training-set mean move from both target vectors, or leave them alone.

    The price fell steadily through both recordings, so a constant negative number is present in
    every raw target.  A model can appear to work by learning that constant and nothing else.
    Subtracting the **training** mean — never the test mean, which would use the future — removes
    the part of the drift a forecaster could have known about, and leaves whatever varies.
    """

    if not adjust:
        return train_target, test_target, 0.0
    drift = float(train_target.mean())
    return train_target - drift, test_target - drift, drift


def nested_region_comparison(
    observations: Sequence[Observation],
    split: SplitIndex,
    *,
    horizon: int,
    ladder: Sequence[tuple[str, tuple[str, ...]]] = NESTED_LADDER,
    source: Literal["future", "past", "contemporaneous"] = "future",
    drift_adjusted: bool = True,
    replicates: int = BLOCK_BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Best quote → top 5 → top 20 → add 21-50 → add 51-200, scored out of sample at each step.

    Each rung's design matrix is the previous rung's plus one region's features, so the reported
    increment is exactly what that region adds *once the nearer book is already accounted for*.
    That, not the level of any single fit, is the question this scan exists to answer.

    The improvement at each step is tested on the **paired squared-error differential** between
    consecutive rungs, observation by observation: a positive mean says the deeper model made
    smaller errors.  Because the target windows overlap heavily, that differential is reported
    with a Newey-West standard error, a within-tape stationary block bootstrap, and a
    non-overlapping block estimate — all three, never one.
    """

    if not observations:
        raise ValueError("at least one observation is required")
    names = sorted(observations[0].features)
    train_positions = _covered(observations, split.train, horizon=horizon, source=source)
    test_positions = _covered(observations, split.test, horizon=horizon, source=source)
    ladder_rows: list[RungResult] = []
    if (
        len(train_positions) < MINIMUM_FIT_OBSERVATIONS
        or len(test_positions) < MINIMUM_FIT_OBSERVATIONS
    ):
        for rung, regions in ladder:
            ladder_rows.append(
                RungResult(
                    rung=rung,
                    regions=tuple(regions),
                    feature_count=len(features_for_regions(names, regions)),
                    penalty=float("nan"),
                    train_n=len(train_positions),
                    test_n=len(test_positions),
                    out_of_sample_r2_vs_training_mean=None,
                    out_of_sample_r2_vs_zero=None,
                    in_sample_r2=None,
                    squared_errors=(),
                )
            )
        return _nested_payload(
            ladder_rows,
            observations,
            test_positions,
            horizon=horizon,
            source=source,
            drift_adjusted=drift_adjusted,
            split=split,
            replicates=replicates,
            seed=seed,
            insufficient=True,
        )

    raw_train = _target_vector(observations, train_positions, horizon=horizon, source=source)
    raw_test = _target_vector(observations, test_positions, horizon=horizon, source=source)
    train_target, test_target, drift = _drift_adjust(raw_train, raw_test, adjust=drift_adjusted)
    training_mean = float(train_target.mean())
    benchmark = np.full(test_target.shape, training_mean, dtype=np.float64)
    # The raw column is scored on the **unadjusted** scale against a no-change forecast of zero.
    # Scoring it against zero on the adjusted scale would silently reproduce the drift-adjusted
    # number, because after adjustment the training mean *is* zero and the two benchmarks
    # coincide. The first run of this scan did exactly that and produced two identical columns.
    raw_zero_benchmark = np.zeros(raw_test.shape, dtype=np.float64)

    for rung, regions in ladder:
        selected = features_for_regions(names, regions)
        train_design = _design_matrix(observations, train_positions, selected)
        test_design = _design_matrix(observations, test_positions, selected)
        penalty = _select_penalty(train_design, train_target, feature_names=selected)
        fit = fit_ridge(
            train_design, train_target, feature_names=selected, penalty=penalty
        )
        predicted = fit.predict(test_design)
        ladder_rows.append(
            RungResult(
                rung=rung,
                regions=tuple(regions),
                feature_count=len(selected),
                penalty=penalty,
                train_n=len(train_positions),
                test_n=len(test_positions),
                out_of_sample_r2_vs_training_mean=_r_squared(test_target, predicted, benchmark),
                out_of_sample_r2_vs_zero=_r_squared(
                    raw_test, predicted + drift, raw_zero_benchmark
                ),
                in_sample_r2=_r_squared(
                    train_target,
                    fit.predict(train_design),
                    np.full(train_target.shape, training_mean, dtype=np.float64),
                ),
                squared_errors=tuple(float(value) for value in (test_target - predicted) ** 2),
            )
        )
    payload = _nested_payload(
        ladder_rows,
        observations,
        test_positions,
        horizon=horizon,
        source=source,
        drift_adjusted=drift_adjusted,
        split=split,
        replicates=replicates,
        seed=seed,
        insufficient=False,
    )
    payload["training_mean_ticks"] = training_mean
    payload["removed_training_drift_ticks"] = drift
    return payload


def _nested_payload(
    rows: Sequence[RungResult],
    observations: Sequence[Observation],
    test_positions: Sequence[int],
    *,
    horizon: int,
    source: str,
    drift_adjusted: bool,
    split: SplitIndex,
    replicates: int,
    seed: int,
    insufficient: bool,
) -> dict[str, Any]:
    test_share_of_tape = (
        len(test_positions) / len(observations) if observations else None
    )
    timestamps = [observations[position].receive_ts_ns for position in test_positions]
    tapes = [observations[position].tape_index for position in test_positions]
    steps: list[dict[str, Any]] = []
    for previous, current in zip(rows, rows[1:], strict=False):
        differential: list[float] = []
        if previous.squared_errors and current.squared_errors:
            differential = [
                before - after
                for before, after in zip(
                    previous.squared_errors, current.squared_errors, strict=True
                )
            ]
        estimate = estimate_mean(
            differential,
            timestamps,
            tapes,
            overlap_seconds=float(horizon),
            replicates=replicates,
            seed=seed,
        )
        improvement = (
            None
            if (
                current.out_of_sample_r2_vs_training_mean is None
                or previous.out_of_sample_r2_vs_training_mean is None
            )
            else current.out_of_sample_r2_vs_training_mean
            - previous.out_of_sample_r2_vs_training_mean
        )
        baseline_mse = (
            sum(previous.squared_errors) / len(previous.squared_errors)
            if previous.squared_errors
            else None
        )
        requirement = required_blocks_for_target(
            differential,
            timestamps,
            tapes,
            overlap_seconds=float(horizon),
            baseline_mean_squared_error=baseline_mse,
            test_share_of_tape=test_share_of_tape,
        )
        steps.append(
            {
                "step": f"{previous.rung} -> {current.rung}",
                "adds_region": current.regions[-1],
                "out_of_sample_r2_improvement": improvement,
                "mean_squared_error_reduction": estimate.mean,
                "n": estimate.n,
                "newey_west_lag_observations": estimate.newey_west_lag,
                "newey_west_standard_error": estimate.newey_west_standard_error,
                "newey_west_t": estimate.newey_west_t,
                "block_bootstrap_standard_error": estimate.block_bootstrap_standard_error,
                "block_bootstrap_t": estimate.block_bootstrap_t,
                "non_overlapping_blocks": estimate.non_overlapping_blocks,
                "non_overlapping_mean": estimate.non_overlapping_mean,
                "non_overlapping_t": estimate.non_overlapping_t,
                "naive_standard_error": estimate.naive_standard_error,
                "naive_inference_valid": False,
                "distinguishable_from_zero": _distinguishable(estimate),
                "baseline_mean_squared_error_ticks_squared": baseline_mse,
                "required_sample_for_one_percent_r2": requirement,
            }
        )
    return {
        "object_category": "estimated",
        "horizon_seconds": horizon,
        "target_source": source,
        "drift_adjusted": drift_adjusted,
        "data_sufficient": not insufficient,
        "train_n": rows[0].train_n if rows else 0,
        "test_n": rows[0].test_n if rows else 0,
        "embargo_seconds": split.embargo_seconds,
        "embargoed_observations": len(split.embargoed),
        "benchmark_note": (
            "out_of_sample_r2_vs_training_mean is the drift-adjusted number and is the one to "
            "read: it asks whether the book beats 'the price keeps drifting as it did in "
            "training'. out_of_sample_r2_vs_zero is the raw number and is flattered by the "
            "session's fall. Step increments are identical under both, because removing a "
            "constant shifts the target and the fitted intercept equally and cancels."
        ),
        "rungs": [
            {
                "rung": row.rung,
                "regions": list(row.regions),
                "feature_count": row.feature_count,
                "ridge_penalty": None if row.penalty != row.penalty else row.penalty,
                "out_of_sample_r2_vs_training_mean": row.out_of_sample_r2_vs_training_mean,
                "out_of_sample_r2_vs_zero": row.out_of_sample_r2_vs_zero,
                "in_sample_r2": row.in_sample_r2,
            }
            for row in rows
        ],
        "steps": steps,
    }


# A current full NSE equity-derivatives session is 09:15-15:40 IST.
SECONDS_PER_SESSION = NSE_EQUITY_DERIVATIVES_CURRENT_SESSION_SECONDS
TARGET_R2_IMPROVEMENT = 0.01


def required_blocks_for_target(
    differential: Sequence[float],
    timestamps: Sequence[int],
    tapes: Sequence[int],
    *,
    overlap_seconds: float,
    baseline_mean_squared_error: float | None,
    test_share_of_tape: float | None = None,
    target_r2_improvement: float = TARGET_R2_IMPROVEMENT,
) -> dict[str, Any]:
    """How much tape would settle this step, from the observed block-to-block variability.

    The question "does the deep book add anything?" is only answerable to the precision the
    sample allows.  This turns that into a number: given how much the squared-error reduction
    varies from one non-overlapping block to the next, how many such blocks would be needed for
    an improvement worth ``target_r2_improvement`` of out-of-sample R-squared to clear a
    two-sided 1.96 bar — and how many full trading sessions that is.

    It is a **planning figure estimated from 22 minutes of one contract**, not a constant.  A
    calmer or more volatile session would move it.
    """

    if not differential or baseline_mean_squared_error is None or baseline_mean_squared_error <= 0:
        return {
            "target_r2_improvement": target_r2_improvement,
            "observed_blocks": 0,
            "required_blocks": None,
            "required_test_seconds": None,
            "required_test_sessions": None,
            "required_tape_sessions": None,
        }
    block_ns = max(1, int(round(overlap_seconds * NANOSECONDS_PER_SECOND)))
    blocks = _block_means(differential, timestamps, tapes, block_ns=block_ns)
    target_effect = target_r2_improvement * baseline_mean_squared_error
    if len(blocks) < 2 or target_effect <= 0:
        return {
            "target_r2_improvement": target_r2_improvement,
            "observed_blocks": len(blocks),
            "required_blocks": None,
            "required_test_seconds": None,
            "required_test_sessions": None,
            "required_tape_sessions": None,
        }
    mean = sum(blocks) / len(blocks)
    variance = sum((value - mean) ** 2 for value in blocks) / (len(blocks) - 1)
    if variance <= 0:
        return {
            "target_r2_improvement": target_r2_improvement,
            "observed_blocks": len(blocks),
            "required_blocks": None,
            "required_test_seconds": None,
            "required_test_sessions": None,
            "required_tape_sessions": None,
        }
    required = (NORMAL_95_CRITICAL_VALUE * sqrt(variance) / target_effect) ** 2
    required_blocks = int(required) + 1
    required_seconds = required_blocks * overlap_seconds
    return {
        "target_r2_improvement": target_r2_improvement,
        "observed_blocks": len(blocks),
        "observed_block_standard_deviation": sqrt(variance),
        "target_effect_ticks_squared": target_effect,
        "required_blocks": required_blocks,
        "required_test_seconds": required_seconds,
        # The test set is what needs the blocks; at this scan's 70/30-with-embargo split the test
        # set is about 12% of the tape, so the tape requirement is far larger than this figure.
        "required_test_sessions": required_seconds / SECONDS_PER_SESSION,
        # The blocks are needed in the *test* set, and this scan's split leaves only a small
        # slice of the tape there once the embargo band is discarded. The tape figure is the one
        # to quote when asking how much recording would settle the question.
        "required_tape_sessions": (
            required_seconds / SECONDS_PER_SESSION / test_share_of_tape
            if test_share_of_tape and test_share_of_tape > 0
            else None
        ),
        "test_share_of_tape": test_share_of_tape,
    }


def _distinguishable(estimate: MeanEstimate) -> bool:
    """Distinguishable from zero only when **all three** dependence-aware estimators agree.

    A single estimator clearing 1.96 on 22 minutes of overlapping windows is not evidence; the
    exploratory SIG-21 scan measured negative controls firing in 31-41% of cells on this exact
    tape.  Requiring the Newey-West statistic, the block bootstrap and the non-overlapping block
    estimate to agree is a deliberately conservative rule, and the individual numbers are all
    reported so a reader can apply a looser one and see what it costs.
    """

    statistics = [
        estimate.newey_west_t,
        estimate.block_bootstrap_t,
        estimate.non_overlapping_t,
    ]
    if any(value is None for value in statistics):
        return False
    return all(abs(float(value or 0.0)) > NORMAL_95_CRITICAL_VALUE for value in statistics) and (
        len({float(value or 0.0) > 0 for value in statistics}) == 1
    )


# ----------------------------------------------------------------------------------------------
# Univariate associations — every feature, every horizon, future / past / contemporaneous
# ----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssociationRow:
    feature: str
    region: str | None
    horizon_seconds: int
    n_blocks: int
    correlation: float | None
    slope_ticks_per_unit: float | None
    t_statistic: float | None


def _block_series(
    observations: Sequence[Observation],
    positions: Sequence[int],
    *,
    feature: str,
    horizon: int,
    source: Literal["future", "past", "contemporaneous"],
    block_ns: int,
) -> tuple[list[float], list[float]]:
    """Average the feature and the response inside disjoint time blocks, never spanning tapes.

    Averaging first is how the overlap is removed *by construction* rather than corrected for.
    It is the estimator to read when the corrected estimators and it disagree.
    """

    buckets: dict[tuple[int, int], tuple[list[float], list[float]]] = {}
    origin: dict[int, int] = {}
    table_name = {
        "future": "future_ticks",
        "past": "past_ticks",
        "contemporaneous": "contemporaneous_ticks",
    }[source]
    for position in positions:
        observation = observations[position]
        table = getattr(observation, table_name)
        if horizon not in table or feature not in observation.features:
            continue
        origin.setdefault(observation.tape_index, observation.receive_ts_ns)
        key = (
            observation.tape_index,
            (observation.receive_ts_ns - origin[observation.tape_index]) // block_ns,
        )
        predictor, response = buckets.setdefault(key, ([], []))
        predictor.append(float(observation.features[feature]))
        response.append(float(table[horizon]))
    predictors: list[float] = []
    responses: list[float] = []
    for _, (predictor, response) in sorted(buckets.items()):
        predictors.append(sum(predictor) / len(predictor))
        responses.append(sum(response) / len(response))
    return predictors, responses


def _ordinary_least_squares(
    predictor: Sequence[float], response: Sequence[float]
) -> tuple[float | None, float | None, float | None]:
    n = len(predictor)
    if n < 3:
        return None, None, None
    mean_x = sum(predictor) / n
    mean_y = sum(response) / n
    centred_x = [value - mean_x for value in predictor]
    centred_y = [value - mean_y for value in response]
    sxx = sum(value * value for value in centred_x)
    syy = sum(value * value for value in centred_y)
    if sxx <= 0 or syy <= 0:
        return None, None, None
    sxy = sum(x * y for x, y in zip(centred_x, centred_y, strict=True))
    slope = sxy / sxx
    correlation = sxy / sqrt(sxx * syy)
    residuals = [y - slope * x for x, y in zip(centred_x, centred_y, strict=True)]
    variance = sum(value * value for value in residuals) / max(n - 2, 1)
    standard_error = sqrt(variance / sxx)
    t_statistic = slope / standard_error if standard_error > 0 else None
    return correlation, slope, t_statistic


def association_table(
    observations: Sequence[Observation],
    *,
    horizons_seconds: Sequence[int] = HORIZONS_SECONDS,
    source: Literal["future", "past", "contemporaneous"] = "future",
    features: Sequence[str] | None = None,
) -> list[AssociationRow]:
    """Every feature against the response at every horizon, on non-overlapping blocks.

    The complete table is emitted — every feature, every horizon, nothing ranked away.  On a
    grid this size a handful of large statistics is the expected outcome under the null, and a
    filtered table would hide exactly that.
    """

    if not observations:
        return []
    names = sorted(features) if features is not None else sorted(observations[0].features)
    names = [name for name in names if name != "midpoint"]
    positions = tuple(range(len(observations)))
    rows: list[AssociationRow] = []
    for horizon in horizons_seconds:
        block_ns = max(1, horizon * NANOSECONDS_PER_SECOND)
        for name in names:
            predictor, response = _block_series(
                observations,
                positions,
                feature=name,
                horizon=horizon,
                source=source,
                block_ns=block_ns,
            )
            correlation, slope, t_statistic = _ordinary_least_squares(predictor, response)
            rows.append(
                AssociationRow(
                    feature=name,
                    region=feature_region(name),
                    horizon_seconds=horizon,
                    n_blocks=len(predictor),
                    correlation=correlation,
                    slope_ticks_per_unit=slope,
                    t_statistic=t_statistic,
                )
            )
    assert_complete_table(
        emitted=len(rows),
        expected=len(names) * len(horizons_seconds),
        name="association table",
    )
    return rows


# ----------------------------------------------------------------------------------------------
# Negative controls — the ones that exposed the problem on this exact tape yesterday
# ----------------------------------------------------------------------------------------------


def _deterministic_permutation(size: int, *, seed: int) -> list[int]:
    order = list(range(size))
    generator = np.random.default_rng(seed)
    generator.shuffle(order)
    return [int(value) for value in order]


def shuffle_times_within_bucket(
    observations: Sequence[Observation], *, seed: int = BOOTSTRAP_SEED
) -> list[Observation]:
    """Re-attach each observation's responses to another instant in the same 30-minute bucket.

    Keeps the book state and the response distribution exactly as they are and destroys only the
    pairing between them.  Anything that still fires afterwards is measuring the session, not the
    book.
    """

    by_bucket: dict[tuple[int, str], list[int]] = {}
    for position, observation in enumerate(observations):
        by_bucket.setdefault((observation.tape_index, observation.time_bucket), []).append(
            position
        )
    shuffled = list(observations)
    for offset, (_key, positions) in enumerate(sorted(by_bucket.items())):
        if len(positions) < 2:
            continue
        permutation = _deterministic_permutation(len(positions), seed=seed + offset)
        for source_index, target_index in enumerate(permutation):
            donor = observations[positions[target_index]]
            original = observations[positions[source_index]]
            shuffled[positions[source_index]] = Observation(
                tape_index=original.tape_index,
                run_id=original.run_id,
                receive_ts_ns=original.receive_ts_ns,
                time_bucket=original.time_bucket,
                features=original.features,
                future_ticks=donor.future_ticks,
                past_ticks=donor.past_ticks,
                contemporaneous_ticks=donor.contemporaneous_ticks,
            )
    return shuffled


_SIDE_SWAPS: tuple[tuple[str, str], ...] = (
    ("bid", "ask"),
    ("ask", "bid"),
)


def permute_side_labels(
    observations: Sequence[Observation], *, seed: int = BOOTSTRAP_SEED
) -> list[Observation]:
    """Mirror the bid and ask labels of a deterministic **half** of the observations.

    If the book's side composition carries anything, destroying which side is which must cost the
    fit something.

    **This control was wrong in the first run of this scan and the defect is worth recording,
    because it is the same shape as the manufactured null found in the SIG-21 exploratory scan.**
    The first version mirrored *every* observation. A refit linear model is exactly equivariant to
    a global mirror — negating a column flips its coefficient's sign, swapping two columns swaps
    two coefficients, and the predictions come out byte-identical. The control reproduced the real
    result to the last decimal and could never have done anything else, whatever the data said.

    Mirroring a *subset* is not a symmetry of the design, so the model cannot relearn it. The
    mirrored and unmirrored observations now disagree about what a positive imbalance means, which
    is exactly the information the control is supposed to remove.
    ``test_side_label_control_is_not_a_symmetry_the_model_can_relearn`` locks this in.
    """

    def swap(name: str) -> str:
        for source, target in _SIDE_SWAPS:
            if f"__{source}_" in name:
                return name.replace(f"__{source}_", f"__{target}_", 1)
        return name

    generator = np.random.default_rng(seed)
    mirror_flags = generator.random(len(observations)) < 0.5
    mirrored: list[Observation] = []
    for observation, mirror in zip(observations, mirror_flags, strict=True):
        if not mirror:
            mirrored.append(observation)
            continue
        swapped: dict[str, float] = {}
        for name, value in observation.features.items():
            target = swap(name)
            # An imbalance carries no side token in its name, so mirroring it means negating it.
            swapped[target] = -value if "imbalance" in name else value
        mirrored.append(
            Observation(
                tape_index=observation.tape_index,
                run_id=observation.run_id,
                receive_ts_ns=observation.receive_ts_ns,
                time_bucket=observation.time_bucket,
                features=swapped,
                future_ticks=observation.future_ticks,
                past_ticks=observation.past_ticks,
                contemporaneous_ticks=observation.contemporaneous_ticks,
            )
        )
    return mirrored


# ----------------------------------------------------------------------------------------------
# Yardstick only — how much structure exists in principle. Never a strategy candidate.
# ----------------------------------------------------------------------------------------------


def _quantile_bins(
    train_design: NDArray[np.float64], *, candidates: int
) -> tuple[NDArray[np.float64], int]:
    """One fixed quantile grid per column, computed on the training design only."""

    probabilities = np.linspace(0.0, 1.0, candidates + 1)[1:-1]
    edges = np.quantile(train_design, probabilities, axis=0)
    return np.asarray(edges, dtype=np.float64), candidates


def _bin_indices(design: NDArray[np.float64], edges: NDArray[np.float64]) -> NDArray[np.int64]:
    """Bin every observation of every column against that column's training quantile edges."""

    rows, columns = design.shape
    indices = np.empty((rows, columns), dtype=np.int64)
    for column in range(columns):
        indices[:, column] = np.searchsorted(edges[:, column], design[:, column], side="right")
    return indices


def fit_yardstick(
    train_design: NDArray[np.float64],
    train_target: NDArray[np.float64],
    test_design: NDArray[np.float64],
    *,
    rounds: int = YARDSTICK_ROUNDS,
    learning_rate: float = YARDSTICK_LEARNING_RATE,
    candidates: int = YARDSTICK_SPLIT_CANDIDATES,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Gradient-boosted depth-one stumps. **A yardstick, never a strategy candidate.**

    Under `D11(c)` and the `SIG-18` logic a black-box model measures how much structure exists in
    principle; anything promoted to a tradeable rule must be sparse and interpretable.  Its
    out-of-sample number is an upper bound on what the linear fits could be missing, and it is a
    result about *measurable structure*, never about the market.

    Every split threshold comes from a quantile grid fixed on the **training** design before
    boosting starts, so the test set never influences where a split is placed.
    """

    intercept = float(train_target.mean())
    train_prediction: NDArray[np.float64] = np.full(
        train_target.shape, intercept, dtype=np.float64
    )
    test_prediction: NDArray[np.float64] = np.full(
        test_design.shape[0], intercept, dtype=np.float64
    )
    rows, columns = train_design.shape
    if rows < 2 * MINIMUM_FIT_OBSERVATIONS or columns == 0:
        return train_prediction, test_prediction

    edges, bins = _quantile_bins(train_design, candidates=candidates)
    train_bins = _bin_indices(train_design, edges)
    test_bins = _bin_indices(test_design, edges)
    # Flatten (row, column) -> a single bincount address, so one call covers every column at once.
    offsets = (np.arange(columns, dtype=np.int64) * bins)[None, :]
    flat_train = (train_bins + offsets).ravel()
    counts = np.bincount(flat_train, minlength=columns * bins).astype(np.float64)
    cumulative_counts = np.cumsum(counts.reshape(columns, bins), axis=1)
    total_count = float(rows)

    for _ in range(rounds):
        residual = train_target - train_prediction
        weights = np.repeat(residual, columns)
        sums = np.bincount(flat_train, weights=weights, minlength=columns * bins)
        cumulative_sums = np.cumsum(sums.reshape(columns, bins), axis=1)
        total_sum = float(residual.sum())
        # Candidate split at bin b keeps bins <= b on the left. The last bin is not a split.
        left_count = cumulative_counts[:, :-1]
        left_sum = cumulative_sums[:, :-1]
        right_count = total_count - left_count
        right_sum = total_sum - left_sum
        viable = (left_count >= 5) & (right_count >= 5)
        gain = np.where(
            viable,
            np.divide(left_sum**2, left_count, out=np.zeros_like(left_sum), where=left_count > 0)
            + np.divide(
                right_sum**2, right_count, out=np.zeros_like(right_sum), where=right_count > 0
            ),
            -np.inf,
        )
        if not np.isfinite(gain).any():
            break
        best = int(np.argmax(gain))
        column, bin_index = divmod(best, gain.shape[1])
        if not np.isfinite(gain[column, bin_index]) or gain[column, bin_index] <= 0:
            break
        left_mean = float(left_sum[column, bin_index] / left_count[column, bin_index])
        right_mean = float(right_sum[column, bin_index] / right_count[column, bin_index])
        train_prediction = train_prediction + learning_rate * np.where(
            train_bins[:, column] <= bin_index, left_mean, right_mean
        )
        test_prediction = test_prediction + learning_rate * np.where(
            test_bins[:, column] <= bin_index, left_mean, right_mean
        )
    return train_prediction, test_prediction


# ----------------------------------------------------------------------------------------------
# Artifact assembly
# ----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TapeInput:
    """One contiguous permitted tape, already replayed into observations."""

    tape_index: int
    run_id: str
    instrument_id: str
    tape_sha256: str
    observations: tuple[Observation, ...]
    depth200_publications: int
    depth20_publications: int
    observed_seconds: float
    failures: Mapping[str, int]


def _summarise_ticks(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "sd": None, "p05": None, "p50": None, "p95": None}
    n = len(values)
    mean = sum(values) / n
    variance = sum((value - mean) ** 2 for value in values) / n
    return {
        "n": n,
        "mean": mean,
        "sd": sqrt(variance),
        "p05": percentile(sorted(values), 0.05),
        "p50": percentile(sorted(values), 0.50),
        "p95": percentile(sorted(values), 0.95),
        "share_up_at_least_one_tick": sum(1 for value in values if value >= 1.0) / n,
        "share_down_at_least_one_tick": sum(1 for value in values if value <= -1.0) / n,
    }


def unconditional_response(
    observations: Sequence[Observation],
    *,
    horizons_seconds: Sequence[int] = HORIZONS_SECONDS,
) -> list[dict[str, Any]]:
    """The response distribution with no conditioning at all — the drift, made visible first."""

    rows: list[dict[str, Any]] = []
    for horizon in horizons_seconds:
        future = [
            observation.future_ticks[horizon]
            for observation in observations
            if horizon in observation.future_ticks
        ]
        past = [
            observation.past_ticks[horizon]
            for observation in observations
            if horizon in observation.past_ticks
        ]
        contemporaneous = [
            observation.contemporaneous_ticks[horizon]
            for observation in observations
            if horizon in observation.contemporaneous_ticks
        ]
        rows.append(
            {
                "horizon_seconds": horizon,
                "future": _summarise_ticks(future),
                "past_mirror": _summarise_ticks(past),
                "contemporaneous": _summarise_ticks(contemporaneous),
            }
        )
    assert_complete_table(
        emitted=len(rows), expected=len(horizons_seconds), name="unconditional response table"
    )
    return rows


def yardstick_comparison(
    observations: Sequence[Observation],
    split: SplitIndex,
    *,
    horizon: int,
    drift_adjusted: bool = True,
) -> dict[str, Any]:
    """The flexible model's out-of-sample number, beside the full linear model's. Yardstick only."""

    names = sorted(observations[0].features) if observations else []
    selected = features_for_regions(names, [region for region, *_ in LEVEL_REGIONS])
    train_positions = _covered(observations, split.train, horizon=horizon, source="future")
    test_positions = _covered(observations, split.test, horizon=horizon, source="future")
    if (
        len(train_positions) < MINIMUM_FIT_OBSERVATIONS
        or len(test_positions) < MINIMUM_FIT_OBSERVATIONS
    ):
        return {
            "object_category": "estimated",
            "role": "yardstick_only_never_a_strategy_candidate",
            "horizon_seconds": horizon,
            "data_sufficient": False,
            "out_of_sample_r2_vs_training_mean": None,
        }
    train_design = _design_matrix(observations, train_positions, selected)
    test_design = _design_matrix(observations, test_positions, selected)
    raw_train = _target_vector(observations, train_positions, horizon=horizon, source="future")
    raw_test = _target_vector(observations, test_positions, horizon=horizon, source="future")
    train_target, test_target, _ = _drift_adjust(raw_train, raw_test, adjust=drift_adjusted)
    _, test_prediction = fit_yardstick(train_design, train_target, test_design)
    benchmark = np.full(test_target.shape, float(train_target.mean()), dtype=np.float64)
    return {
        "object_category": "estimated",
        "role": "yardstick_only_never_a_strategy_candidate",
        "role_note": (
            "D11(c) and the SIG-18 logic: a black-box model measures how much structure exists "
            "in principle. It is not a candidate, its number is not a result, and nothing may be "
            "promoted from it. It is here so that a near-zero linear number can be read as "
            "'there is little to find' rather than 'the linear form was too restrictive'."
        ),
        "horizon_seconds": horizon,
        "drift_adjusted": drift_adjusted,
        "data_sufficient": True,
        "feature_count": len(selected),
        "boosting_rounds": YARDSTICK_ROUNDS,
        "train_n": len(train_positions),
        "test_n": len(test_positions),
        "out_of_sample_r2_vs_training_mean": _r_squared(test_target, test_prediction, benchmark),
    }


def build_normal_activity_artifact(
    tapes: Sequence[TapeInput],
    *,
    code_commit: str | None,
    horizons_seconds: Sequence[int] = HORIZONS_SECONDS,
    replicates: int = BLOCK_BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
    include_yardstick: bool = True,
) -> dict[str, Any]:
    """The complete scan. Every table complete, nothing filtered to its interesting rows."""

    observations = [
        observation for tape in tapes for observation in tape.observations
    ]
    observations.sort(key=lambda item: (item.tape_index, item.receive_ts_ns))
    split = chronological_embargoed_split(observations) if observations else SplitIndex(
        (), (), (), EMBARGO_SECONDS, ()
    )
    feature_names = sorted(observations[0].features) if observations else []

    # Raw and drift-adjusted results are reported as two columns of one table rather than two
    # tables. Subtracting the training-set drift shifts the target and the fitted intercept by the
    # same constant, so every residual — and therefore every step increment — is *identical*
    # under both. What differs is only the benchmark the fit is scored against:
    #   `out_of_sample_r2_vs_zero`          — raw: beat "the price does not move". Flattered
    #                                          by the session's fall.
    #   `out_of_sample_r2_vs_training_mean` — drift-adjusted: beat "the price keeps drifting as it
    #                                          did in training". This is the one to read.
    # Emitting them as two tables would have looked like two results and been one.
    nested: dict[str, Any] = {}
    for label, ladder in (("level_index", NESTED_LADDER), ("price_distance", DISTANCE_LADDER)):
        if not observations:
            nested[label] = []
            continue
        nested[label] = [
            nested_region_comparison(
                observations,
                split,
                horizon=horizon,
                ladder=ladder,
                drift_adjusted=True,
                replicates=replicates,
                seed=seed,
            )
            for horizon in horizons_seconds
        ]

    controls: dict[str, Any] = {}
    if observations:
        control_sets: tuple[tuple[str, Sequence[Observation], str], ...] = (
            (
                "time_shuffle_within_30_minute_bucket",
                shuffle_times_within_bucket(observations, seed=seed),
                "future",
            ),
            (
                "side_label_permutation",
                permute_side_labels(observations, seed=seed),
                "future",
            ),
            ("past_return_mirror", observations, "past"),
            ("contemporaneous_leg", observations, "contemporaneous"),
        )
        for name, control_observations, source in control_sets:
            control_split = chronological_embargoed_split(control_observations)
            controls[name] = [
                nested_region_comparison(
                    control_observations,
                    control_split,
                    horizon=horizon,
                    source=source,  # type: ignore[arg-type]
                    drift_adjusted=True,
                    replicates=replicates,
                    seed=seed,
                )
                for horizon in horizons_seconds
            ]

    associations = {
        source: [
            {
                "feature": row.feature,
                "region": row.region,
                "horizon_seconds": row.horizon_seconds,
                "n_non_overlapping_blocks": row.n_blocks,
                "correlation": row.correlation,
                "slope_ticks_per_unit": row.slope_ticks_per_unit,
                "t_statistic": row.t_statistic,
            }
            for row in association_table(
                observations,
                horizons_seconds=horizons_seconds,
                source=source,
            )
        ]
        for source in ("future", "past", "contemporaneous")
    }

    yardstick = (
        [
            yardstick_comparison(observations, split, horizon=horizon)
            for horizon in horizons_seconds
        ]
        if include_yardstick and observations
        else []
    )

    return {
        "protocol": {
            "exploratory_scan_id": EXPLORATORY_SCAN_ID,
            "confirmatory_eligible": CONFIRMATORY_ELIGIBLE,
            "sample_role": SAMPLE_ROLE,
            "is_part_of_h_sig21": False,
            "relationship_to_h_sig21": (
                "None. This scan shares two source tapes and the depth20 mid-price target "
                "convention with H-SIG21 and nothing else: no registered family, no thresholds, "
                "no strata, no anomaly detector, no verdict vocabulary. H-SIG21's 384-cell "
                "registration is untouched and no result here may be cited against it."
            ),
            "sig21_registering_commit": SIG21_REGISTERING_COMMIT,
            "sig21_registering_commit_pushed": SIG21_REGISTERING_COMMIT_TIMESTAMP_IST,
            "eligibility_justification": (
                "Both tapes were captured at 13:09 and 13:20 IST, about an hour and fifty "
                "minutes before the H-SIG21 registering commit was pushed at 15:00:42 IST. "
                "H-SIG21 §1.5 admits only tape collected after that commit into its first "
                "outcome sample and §1.2 already excludes these tapes' post-event price paths, "
                "so they were permanently outside any confirmatory sample before this scan "
                "existed. Looking at them costs nothing that was not already spent."
            ),
            "code_commit": code_commit,
            "horizons_seconds": list(horizons_seconds),
            "tick_size_rupees": FUTURES_TICK_SIZE,
            "object_categories": {
                "region totals, imbalances, shape measures, differences": (
                    "deterministically_derived"
                ),
                "every fit, R-squared, standard error, interval and test statistic": "estimated",
                "average order size (quantity / order count)": "proxy",
                "per-order identity, per-order lifetime, true order flow": "unidentified",
            },
        },
        "tapes": [
            {
                "tape_index": tape.tape_index,
                "run_id": tape.run_id,
                "instrument_id": tape.instrument_id,
                "tape_sha256": tape.tape_sha256,
                "depth200_publications": tape.depth200_publications,
                "depth20_publications": tape.depth20_publications,
                "observed_seconds": tape.observed_seconds,
                "usable_observations": len(tape.observations),
                "drop_reasons": dict(tape.failures),
            }
            for tape in tapes
        ],
        "totals": {
            "observations": len(observations),
            "features_per_observation": len(feature_names),
            "level_regions": [name for name, *_ in LEVEL_REGIONS],
            "distance_regions": [name for name, *_ in DISTANCE_REGIONS],
            "flow_lookbacks": [name for name, _ in FLOW_LOOKBACKS],
        },
        "split": {
            "train_n": len(split.train),
            "test_n": len(split.test),
            "embargoed_n": len(split.embargoed),
            "embargo_seconds": split.embargo_seconds,
            "train_fraction": TRAIN_FRACTION,
            "per_tape_boundaries": [
                {
                    "tape_index": int(tape_index),
                    "train_end_ts_ns": start,
                    "test_start_after_ts_ns": end,
                }
                for tape_index, start, end in split.boundaries
            ],
            "note": (
                "Each tape is split chronologically at 70% and an embargo band longer than the "
                "longest target horizon is discarded from both sides, so no training "
                "observation's target window is still open when the test set begins."
            ),
        },
        "unconditional_response": unconditional_response(
            observations, horizons_seconds=horizons_seconds
        ),
        "nested_region_comparison": nested,
        "negative_controls": controls,
        "associations": associations,
        "yardstick": yardstick,
        "feature_names": feature_names,
    }


def nested_rows(artifact: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten every nested-ladder rung and step to one JSONL row, complete, nothing filtered."""

    protocol = artifact["protocol"]
    rows: list[dict[str, Any]] = []
    sources: list[tuple[str, str, Any]] = [
        ("real", key, block) for key, block in artifact["nested_region_comparison"].items()
    ]
    sources.extend(
        ("negative_control", key, block) for key, block in artifact["negative_controls"].items()
    )
    for family, key, blocks in sources:
        for block in blocks:
            base = {
                "exploratory_scan_id": protocol["exploratory_scan_id"],
                "confirmatory_eligible": protocol["confirmatory_eligible"],
                "family": family,
                "ladder": key,
                "horizon_seconds": block["horizon_seconds"],
                "target_source": block["target_source"],
                "drift_adjusted": block["drift_adjusted"],
                "data_sufficient": block["data_sufficient"],
                "train_n": block["train_n"],
                "test_n": block["test_n"],
            }
            for rung in block["rungs"]:
                flattened = {**base, "row_type": "rung", **rung}
                flattened["regions"] = ",".join(rung["regions"])
                rows.append(flattened)
            for step in block["steps"]:
                rows.append({**base, "row_type": "step", **step})
    return rows


def association_rows(artifact: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten the complete association tables to one JSONL row per feature-horizon-source."""

    protocol = artifact["protocol"]
    rows: list[dict[str, Any]] = []
    for source, table in artifact["associations"].items():
        for row in table:
            rows.append(
                {
                    "exploratory_scan_id": protocol["exploratory_scan_id"],
                    "confirmatory_eligible": protocol["confirmatory_eligible"],
                    "target_source": source,
                    **row,
                }
            )
    return rows
