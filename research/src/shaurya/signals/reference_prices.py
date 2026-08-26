"""Reference-price ladder and touch-relative re-derivation — `D38`, sections A.3 and A.4.

`TOUCH-03` declares four reference prices and requires that each be applied on **both** sides of
the regression: as the return target, and as the reference against which the predictors are
measured.  Reporting only one side would confound regressor noise with dependent-variable noise —
if the displayed mid is a noisy reading of where trading is, a predictor measured against it will
look weak whether the predictor is weak or not.

The ladder:

===========================  ============================  ==================================
reference                    definition                    object category
===========================  ============================  ==================================
``displayed_mid``            depth20 ``(bid + ask) / 2``    deterministically derived
``last_trade``               the last observed print        observed
``effective_touch_mid``      ``TOUCH-02`` bounds, midpoint  proxy
``microprice``               ``MICRO-01`` size weighting    deterministically derived
===========================  ============================  ==================================

`TOUCH-04` re-derives the three book objects the horse race actually races — multi-level CCZ
order flow imbalance, level-one queue imbalance and the microprice — relative to the effective
touch rather than the displayed level one.  The re-keying is the substance:
:func:`touch_relative_state` maps a displayed book onto **tick-distance bands measured outward
from the effective touch**, so band ``m`` means the same distance from where trading is at every
anchor.  Under the displayed rank-keying of `ID-CCZ-01`, one best-quote move relabels every level
at once; anchoring the bands to the effective touch removes that relabelling, at the cost of
depending on a proxy (`ID-TOUCH-01`).

Every reference price is emitted as **missing** where it is undefined.  Nothing here ever falls
back to the displayed touch — that is `VAL-TOUCH-02`, and silently substituting the status quo
baseline for the object under test would make the whole comparison vacuous.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import Any, Final

from shaurya.analytics.depth_thinning_analysis import BookState
from shaurya.signals.deep_book_ofi import FUTURES_TICK_SIZE
from shaurya.signals.effective_touch import (
    ID_TOUCH_01,
    ID_TOUCH_01_LIMITATION,
    EffectiveTouch,
    EffectiveTouchSeries,
    TradePrint,
)
from shaurya.signals.microprice import simple_microprice

SPECIFICATION_ID: Final = "D38 / TOUCH-METRICS-2026-08-20"
DESIGN_DOCUMENT: Final = "research/docs/TOUCH-METRICS-SPEC-2026-08-20.md"


class ReferencePrice(StrEnum):
    """`TOUCH-03`: the four reference prices, evaluated identically and reported side by side."""

    DISPLAYED_MID = "displayed_mid"
    LAST_TRADE = "last_trade"
    EFFECTIVE_TOUCH_MID = "effective_touch_mid"
    MICROPRICE = "microprice"


#: `TOUCH-03`.  The full declared ladder.  No member is dropped; a reference that is undefined on
#: a tape is reported as uncovered, not omitted.
REFERENCE_PRICE_LADDER: Final = tuple(member.value for member in ReferencePrice)
#: The status quo baseline, retained so post-D38 cells stay comparable with the 11:30 horse race.
BASELINE_REFERENCE: Final = ReferencePrice.DISPLAYED_MID.value

#: `TOUCH-04`.  Width of one tick-distance band measured outward from the effective touch.  The
#: median displayed spread on this feed is tens of ticks (`ID-CKS-02`), so a one-tick band would
#: leave almost every band empty; five ticks keeps bands populated while staying far finer than
#: the spread itself.
TOUCH_RELATIVE_BAND_TICKS: Final = 5.0
#: `TOUCH-04`.  Half-width of the depth band used for the touch-relative queue imbalance and
#: microprice, in ticks, measured outward from each effective bound.
TOUCH_RELATIVE_DEPTH_BAND_TICKS: Final = 25.0


# ------------------------------------------------------------------------------ the price series


@dataclass(frozen=True, slots=True)
class PricePath:
    """A causal as-of price path. Never interpolates forward and never extrapolates past the end.

    The right-edge refusal is deliberate and is the same rule as :class:`Depth20MidSeries`: an
    endpoint past the final observation would silently resolve back to it and fabricate a return
    of exactly zero, which reads as a measurement rather than as missing coverage.
    """

    reference: str
    timestamps: tuple[int, ...]
    prices: tuple[float, ...]

    def __len__(self) -> int:
        return len(self.timestamps)

    @property
    def coverage_start_ts_ns(self) -> int | None:
        return self.timestamps[0] if self.timestamps else None

    @property
    def coverage_end_ts_ns(self) -> int | None:
        return self.timestamps[-1] if self.timestamps else None

    def as_of(self, target_ts_ns: int) -> float | None:
        if not self.timestamps:
            return None
        if target_ts_ns < self.timestamps[0] or target_ts_ns > self.timestamps[-1]:
            return None
        position = bisect_right(self.timestamps, target_ts_ns) - 1
        return self.prices[position] if position >= 0 else None

    def return_ticks(self, start_ts_ns: int, end_ts_ns: int) -> float | None:
        start = self.as_of(start_ts_ns)
        end = self.as_of(end_ts_ns)
        if start is None or end is None or end_ts_ns <= start_ts_ns:
            return None
        return (end - start) / FUTURES_TICK_SIZE


def _append(timestamps: list[int], prices: list[float], stamp: int, value: float) -> None:
    if not isfinite(value):
        return
    if timestamps and stamp <= timestamps[-1]:
        return
    timestamps.append(stamp)
    prices.append(value)


def build_displayed_mid_path(states: Sequence[BookState]) -> PricePath:
    """`TOUCH-03` (i): the status quo baseline, the displayed depth20 midpoint."""

    timestamps: list[int] = []
    prices: list[float] = []
    for state in states:
        bid, ask = state.best_bid, state.best_ask
        if bid is None or ask is None or bid >= ask:
            continue
        _append(timestamps, prices, state.receive_ts_ns, (bid + ask) / 2.0)
    return PricePath(ReferencePrice.DISPLAYED_MID.value, tuple(timestamps), tuple(prices))


def build_last_trade_path(prints: Sequence[TradePrint]) -> PricePath:
    """`TOUCH-03` (ii): the last traded price. The only **observed** member of the ladder."""

    timestamps: list[int] = []
    prices: list[float] = []
    for item in sorted(prints, key=lambda value: value.receive_ts_ns):
        _append(timestamps, prices, item.receive_ts_ns, item.price)
    return PricePath(ReferencePrice.LAST_TRADE.value, tuple(timestamps), tuple(prices))


def build_microprice_path(states: Sequence[BookState]) -> PricePath:
    """`TOUCH-03` (iv): the `MICRO-01` size-weighted microprice on the displayed level one."""

    timestamps: list[int] = []
    prices: list[float] = []
    for state in states:
        if not state.bids or not state.asks:
            continue
        bid, bid_quantity, _ = state.bids[0]
        ask, ask_quantity, _ = state.asks[0]
        value = simple_microprice(
            bid=float(bid),
            bid_quantity=float(bid_quantity),
            ask=float(ask),
            ask_quantity=float(ask_quantity),
        )
        if value is None:
            continue
        _append(timestamps, prices, state.receive_ts_ns, value)
    return PricePath(ReferencePrice.MICROPRICE.value, tuple(timestamps), tuple(prices))


def build_effective_touch_mid_path(
    series: EffectiveTouchSeries, anchors: Sequence[int]
) -> PricePath:
    """`TOUCH-03` (iii): the `TOUCH-02` effective-touch midpoint, sampled at the given anchors.

    An anchor whose touch is undefined contributes **no point** to the path.  It is not carried
    forward from the previous anchor and it is never replaced by the displayed mid — the as-of
    rule then resolves such an anchor to the last defined effective touch, whose staleness the
    caller already reports, rather than to a fabricated value (`VAL-TOUCH-02`).
    """

    timestamps: list[int] = []
    prices: list[float] = []
    for anchor in sorted(anchors):
        mid = series.at(anchor).mid
        if mid is None:
            continue
        _append(timestamps, prices, anchor, mid)
    return PricePath(ReferencePrice.EFFECTIVE_TOUCH_MID.value, tuple(timestamps), tuple(prices))


def build_reference_price_paths(
    *,
    depth20_states: Sequence[BookState],
    prints: Sequence[TradePrint],
    effective_touch: EffectiveTouchSeries,
    anchors: Sequence[int],
) -> dict[str, PricePath]:
    """`TOUCH-03`: the complete ladder, built once and reported side by side."""

    return {
        ReferencePrice.DISPLAYED_MID.value: build_displayed_mid_path(depth20_states),
        ReferencePrice.LAST_TRADE.value: build_last_trade_path(prints),
        ReferencePrice.EFFECTIVE_TOUCH_MID.value: build_effective_touch_mid_path(
            effective_touch, anchors
        ),
        ReferencePrice.MICROPRICE.value: build_microprice_path(depth20_states),
    }


def reference_price_coverage(paths: Mapping[str, PricePath]) -> dict[str, Any]:
    """`VAL-TOUCH-03`: every declared reference must produce a comparable, complete cell set."""

    missing = [name for name in REFERENCE_PRICE_LADDER if name not in paths]
    if missing:
        raise ValueError(f"reference-price ladder is incomplete: {missing}")
    return {
        "requirement": "TOUCH-03",
        "specification_id": SPECIFICATION_ID,
        "ladder": list(REFERENCE_PRICE_LADDER),
        "baseline_reference": BASELINE_REFERENCE,
        "applied_on_both_sides_of_the_regression": True,
        "paths": {
            name: {
                "points": len(paths[name]),
                "coverage_start_ts_ns": paths[name].coverage_start_ts_ns,
                "coverage_end_ts_ns": paths[name].coverage_end_ts_ns,
                "object_category": REFERENCE_OBJECT_CATEGORY[name],
            }
            for name in REFERENCE_PRICE_LADDER
        },
        "limitation_id": ID_TOUCH_01,
        "limitation": ID_TOUCH_01_LIMITATION,
    }


REFERENCE_OBJECT_CATEGORY: Final = {
    ReferencePrice.DISPLAYED_MID.value: "deterministically_derived",
    ReferencePrice.LAST_TRADE.value: "observed",
    ReferencePrice.EFFECTIVE_TOUCH_MID.value: "proxy",
    ReferencePrice.MICROPRICE.value: "deterministically_derived",
}


# --------------------------------------------------------------------------- TOUCH-04 re-keying


def _band_index(distance_ticks: float, band_ticks: float) -> int:
    """Bands are half-open ``[(m-1)w, mw)`` outward from the reference bound; band 1 is nearest."""

    return int(distance_ticks // band_ticks) + 1


def touch_relative_state(
    state: BookState,
    touch: EffectiveTouch,
    *,
    levels: int,
    band_ticks: float = TOUCH_RELATIVE_BAND_TICKS,
) -> BookState | None:
    """`TOUCH-04`: re-key one displayed book onto tick-distance bands from the effective touch.

    Band ``m`` on the bid side aggregates displayed bid depth whose distance below
    ``effective_bid`` falls in ``[(m-1)w, mw)``; the ask side is the mirror above ``effective_ask``.
    The returned state has exactly ``levels`` entries per side, with a **fixed** representative
    price per band, so the rank-keyed CCZ comparison across consecutive states now compares the
    same distance from the touch rather than the same displayed rank.

    Displayed depth strictly inside the effective touch is excluded: it is on the wrong side of
    the price trading has revealed, and folding it into band one would make the band's own sign
    ambiguous.  Returns ``None`` where the touch is undefined — never a displayed-touch fallback.
    """

    if levels < 1:
        raise ValueError("level count must be positive")
    if band_ticks <= 0:
        raise ValueError("band width must be positive")
    if not touch.defined:
        return None
    effective_bid = touch.effective_bid
    effective_ask = touch.effective_ask
    assert effective_bid is not None and effective_ask is not None
    bid_bands = [0.0] * levels
    ask_bands = [0.0] * levels
    bid_orders = [0] * levels
    ask_orders = [0] * levels
    for price, quantity, orders in state.bids:
        distance = (effective_bid - float(price)) / FUTURES_TICK_SIZE
        if distance < 0.0:
            continue
        band = _band_index(distance, band_ticks)
        if band <= levels:
            bid_bands[band - 1] += float(quantity)
            bid_orders[band - 1] += int(orders)
    for price, quantity, orders in state.asks:
        distance = (float(price) - effective_ask) / FUTURES_TICK_SIZE
        if distance < 0.0:
            continue
        band = _band_index(distance, band_ticks)
        if band <= levels:
            ask_bands[band - 1] += float(quantity)
            ask_orders[band - 1] += int(orders)
    step = band_ticks * FUTURES_TICK_SIZE
    return BookState(
        channel=state.channel,
        receive_ts_ns=state.receive_ts_ns,
        receive_sequence=state.receive_sequence,
        connection_epoch=state.connection_epoch,
        bids=tuple(
            (effective_bid - index * step, int(round(bid_bands[index])), bid_orders[index])
            for index in range(levels)
        ),
        asks=tuple(
            (effective_ask + index * step, int(round(ask_bands[index])), ask_orders[index])
            for index in range(levels)
        ),
        rows_in_burst=state.rows_in_burst,
        quality_flags=state.quality_flags,
    )


def _banded_depth(
    ladder: Sequence[tuple[float, int, int]],
    *,
    bound: float,
    band_ticks: float,
    side: str,
) -> float:
    total = 0.0
    for price, quantity, _orders in ladder:
        distance = (
            (bound - float(price)) if side == "bid" else (float(price) - bound)
        ) / FUTURES_TICK_SIZE
        if 0.0 <= distance < band_ticks:
            total += float(quantity)
    return total


def touch_relative_queue_imbalance(
    state: BookState,
    touch: EffectiveTouch,
    *,
    band_ticks: float = TOUCH_RELATIVE_DEPTH_BAND_TICKS,
) -> float | None:
    """`TOUCH-04`: queue imbalance of the depth adjacent to the effective touch, not to L1.

    `ID-CKS-02` established that the displayed level-one queues are the outermost band's size, not
    touch depth.  This measures the displayed depth lying within ``band_ticks`` outward of each
    effective bound, which is the closest observable analogue of the touch queues.
    """

    if not touch.defined:
        return None
    effective_bid = touch.effective_bid
    effective_ask = touch.effective_ask
    assert effective_bid is not None and effective_ask is not None
    bid = _banded_depth(state.bids, bound=effective_bid, band_ticks=band_ticks, side="bid")
    ask = _banded_depth(state.asks, bound=effective_ask, band_ticks=band_ticks, side="ask")
    total = bid + ask
    if total <= 0.0:
        return None
    return (bid - ask) / total


def touch_relative_microprice_tilt_ticks(
    state: BookState,
    touch: EffectiveTouch,
    *,
    band_ticks: float = TOUCH_RELATIVE_DEPTH_BAND_TICKS,
) -> float | None:
    """`TOUCH-04`: the `MICRO-01` weighting applied to the effective bounds and their band depth."""

    if not touch.defined:
        return None
    effective_bid = touch.effective_bid
    effective_ask = touch.effective_ask
    assert effective_bid is not None and effective_ask is not None
    bid = _banded_depth(state.bids, bound=effective_bid, band_ticks=band_ticks, side="bid")
    ask = _banded_depth(state.asks, bound=effective_ask, band_ticks=band_ticks, side="ask")
    value = simple_microprice(
        bid=effective_bid, bid_quantity=bid, ask=effective_ask, ask_quantity=ask
    )
    if value is None:
        return None
    return (value - (effective_bid + effective_ask) / 2.0) / FUTURES_TICK_SIZE


def touch_relative_metadata(
    *,
    band_ticks: float = TOUCH_RELATIVE_BAND_TICKS,
    depth_band_ticks: float = TOUCH_RELATIVE_DEPTH_BAND_TICKS,
) -> dict[str, Any]:
    """The `TOUCH-04` block every re-derived artifact carries."""

    return {
        "requirement": "TOUCH-04",
        "specification_id": SPECIFICATION_ID,
        "design_document": DESIGN_DOCUMENT,
        "re_derived": ["ccz_multi_level_ofi", "l1_queue_imbalance", "microprice"],
        "level_keying": "tick_distance_bands_outward_from_the_effective_touch",
        "band_ticks": band_ticks,
        "depth_band_ticks": depth_band_ticks,
        "displayed_depth_inside_the_effective_touch": "excluded",
        "undefined_touch": "propagated_as_missing_never_the_displayed_touch",
        "object_category": "proxy",
        "removes": (
            "the ID-CCZ-01 rank relabelling: a band means the same distance from where trading is "
            "at every anchor, so one best-quote move no longer relabels every level at once"
        ),
        "introduces": ID_TOUCH_01_LIMITATION,
        "limitation_id": ID_TOUCH_01,
    }
