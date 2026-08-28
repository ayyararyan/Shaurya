"""Effective touch reconstruction — `D38 / TOUCH-METRICS-2026-08-20`, section A.

Amendment `ID-CKS-02` measured a median displayed spread of 100-134 ticks and roughly half of
all executions printing strictly inside the displayed best bid/ask.  Every book-derived
predictor in this repository is defined *relative to the touch*.  If the displayed level one is
not the touch, none of them has yet had a fair test.

This module supplies the two measurements that decide the question:

* `TOUCH-01` — :func:`print_location_diagnostics` classifies every observed trade print against
  the contemporaneous displayed level one (strictly inside / at bid / at ask / strictly outside)
  and reports the distribution overall, by hour and by displayed-spread bucket.  It is a
  **factual measurement** and is reported unchanged whether or not it supports the hypothesis.
* `TOUCH-02` — :class:`EffectiveTouchSeries` estimates the touch that trading actually reveals,
  over a rolling **strictly causal** window of prints classified by
  :mod:`shaurya.data.trade_direction`:

  ``effective_ask <= min(buyer-initiated prints)`` and
  ``effective_bid >= max(seller-initiated prints)``.

  Only prints strictly **before** the anchor may enter.  Where the estimator is undefined the
  result is emitted as missing; it never silently falls back to the displayed touch.

Trade primitives are reused, not reinvented: sides come from the capture-time DAT-14
classification carried on the tape rows, and the contemporaneous displayed quote comes from the
``trade_quote_bid`` / ``trade_quote_ask`` fields that the same classifier already aligned under
``latest-complete-depth-before-print-v1``.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import Any, Final

from shaurya.data import TRADE_ALIGNMENT_VERSION, TRADE_CLASSIFIER_VERSION

from shaurya.analytics.depth_thinning_analysis import parse_receive_ts_ns
from shaurya.signals.deep_book_ofi import FUTURES_TICK_SIZE

SPECIFICATION_ID: Final = "D38 / TOUCH-METRICS-2026-08-20"
DESIGN_DOCUMENT: Final = "research/docs/legacy/TOUCH-METRICS-SPEC-2026-08-20.md"

#: `TOUCH-02`.  Rolling causal windows over which the effective touch is estimated, in seconds.
#: Every declared window is evaluated and reported; none is dropped.
EFFECTIVE_TOUCH_WINDOWS_SECONDS: Final = (2.0, 5.0, 10.0, 30.0, 60.0)
#: The primary window.  At the measured print rate of roughly 0.7 prints per second a shorter
#: window frequently contains no print on one of the two sides, which is a coverage limit rather
#: than a modelling choice; coverage is reported for every declared window.
PRIMARY_EFFECTIVE_TOUCH_WINDOW: Final = 10.0

#: `TOUCH-01`.  Upper edges of the displayed-spread buckets, in ticks.  The last bucket is open.
SPREAD_BUCKET_EDGES_TICKS: Final = (2.0, 10.0, 50.0, 100.0, 150.0, 200.0)

IST_OFFSET_SECONDS: Final = 19_800
NANOSECONDS_PER_SECOND: Final = 1_000_000_000

ID_TOUCH_01: Final = "ID-TOUCH-01"
ID_TOUCH_01_LIMITATION: Final = (
    "ID-TOUCH-01: the effective touch is a bound estimated from executed prints, not an observed "
    "quote. Undisplayed liquidity is never published on this feed, so effective_bid and "
    "effective_ask are the tightest prices trading has revealed inside the rolling causal "
    "window, not the true best quotes. The estimate is stale by construction between prints, and "
    "its staleness is reported per anchor. It is a proxy for the touch, and stays labelled as a "
    "proxy wherever it is used."
)


class PrintLocation(StrEnum):
    """`TOUCH-01`: where an execution printed relative to the contemporaneous displayed quote."""

    STRICTLY_INSIDE = "strictly_inside"
    AT_BID = "at_bid"
    AT_ASK = "at_ask"
    STRICTLY_OUTSIDE = "strictly_outside"


PRINT_LOCATIONS: Final = tuple(location.value for location in PrintLocation)


def classify_print_location(
    *, price: float, displayed_bid: float, displayed_ask: float
) -> PrintLocation:
    """Classify one print against one displayed quote.

    Comparison is on the quantised tick grid rather than on raw floats: the Full packet encodes
    its prices as binary32 and the depth channels as binary64, so ``24252.900390625`` and
    ``24252.9`` are the same exchange price and must compare equal at the touch.  Half-tick
    rounding is exact for the 0.05 rupee NSE tick at these price levels.
    """

    if displayed_bid >= displayed_ask:
        raise ValueError("displayed quote is crossed or locked")
    ticks = round(price / FUTURES_TICK_SIZE)
    bid_ticks = round(displayed_bid / FUTURES_TICK_SIZE)
    ask_ticks = round(displayed_ask / FUTURES_TICK_SIZE)
    if ticks == bid_ticks:
        return PrintLocation.AT_BID
    if ticks == ask_ticks:
        return PrintLocation.AT_ASK
    if bid_ticks < ticks < ask_ticks:
        return PrintLocation.STRICTLY_INSIDE
    return PrintLocation.STRICTLY_OUTSIDE


@dataclass(frozen=True, slots=True)
class TradePrint:
    """One observed execution, with its capture-time side and its displayed-quote context."""

    receive_ts_ns: int
    price: float
    quantity: float
    side: str | None
    displayed_bid: float | None
    displayed_ask: float | None
    quote_channel: str | None
    quote_age_ms: float | None
    location: PrintLocation | None
    spread_ticks: float | None
    degraded: bool
    coalesced: bool

    @property
    def signed(self) -> bool:
        return self.side in {"buy", "sell"}

    @property
    def ist_hour(self) -> int:
        seconds = self.receive_ts_ns // NANOSECONDS_PER_SECOND + IST_OFFSET_SECONDS
        return int(seconds // 3_600 % 24)


@dataclass(frozen=True, slots=True)
class TradePrintSeries:
    """Every observed print on one tape, in capture order, with its exclusion accounting."""

    prints: tuple[TradePrint, ...]
    timestamps: tuple[int, ...]
    schema_packets: int
    excluded_no_increment: int
    excluded_missing_classifier_version: int
    excluded_wrong_classifier_version: int
    excluded_missing_alignment_version: int
    excluded_wrong_alignment_version: int
    excluded_unusable_price: int
    without_displayed_quote: int

    def __len__(self) -> int:
        return len(self.prints)


def _positive(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) and result > 0.0 else None


def build_trade_prints(rows: Sequence[Mapping[str, Any]]) -> TradePrintSeries:
    """Collect every observed positive-volume print, keeping unclassified prints as evidence.

    `TOUCH-01` classifies *every* print, including those the DAT-14 quote rule could not sign, so
    degraded prints are retained here and filtered only where a side is actually required.  The
    displayed quote is the one the capture-time classifier already aligned to the print; no new
    alignment rule is introduced.
    """

    collected: list[TradePrint] = []
    schema_packets = 0
    no_increment = 0
    missing_classifier = 0
    wrong_classifier = 0
    missing_alignment = 0
    wrong_alignment = 0
    unusable_price = 0
    without_quote = 0
    for row in rows:
        if row.get("event_type") != "full":
            continue
        if not any(
            key in row
            for key in (
                "trade_side",
                "trade_classifier_version",
                "trade_alignment_version",
                "trade_classification_degraded",
                "trade_coalesced",
            )
        ):
            continue
        schema_packets += 1
        increment = row.get("cumulative_volume_increment")
        if increment is None or float(increment) <= 0:
            no_increment += 1
            continue
        classifier_version = row.get("trade_classifier_version")
        if classifier_version is None:
            missing_classifier += 1
            continue
        if classifier_version != TRADE_CLASSIFIER_VERSION:
            wrong_classifier += 1
            continue
        alignment_version = row.get("trade_alignment_version")
        if alignment_version is None:
            missing_alignment += 1
            continue
        if alignment_version != TRADE_ALIGNMENT_VERSION:
            wrong_alignment += 1
            continue
        price = _positive(row.get("last_price"))
        stamp = row.get("receive_ts")
        if price is None or not isinstance(stamp, str):
            unusable_price += 1
            continue
        bid = _positive(row.get("trade_quote_bid"))
        ask = _positive(row.get("trade_quote_ask"))
        location: PrintLocation | None = None
        spread: float | None = None
        if bid is None or ask is None or bid >= ask:
            bid = ask = None
            without_quote += 1
        else:
            location = classify_print_location(price=price, displayed_bid=bid, displayed_ask=ask)
            # On the quantised grid, as in ``classify_print_location``: the raw float difference
            # of two binary64 prices puts a genuine two-tick spread at 1.9999 ticks and into the
            # wrong bucket.
            spread = float(round(ask / FUTURES_TICK_SIZE) - round(bid / FUTURES_TICK_SIZE))
        side = row.get("trade_side")
        channel = row.get("trade_quote_channel")
        age = row.get("trade_quote_age_ms")
        collected.append(
            TradePrint(
                receive_ts_ns=parse_receive_ts_ns(stamp),
                price=price,
                quantity=float(increment),
                side=side if side in {"buy", "sell"} else None,
                displayed_bid=bid,
                displayed_ask=ask,
                quote_channel=channel if isinstance(channel, str) else None,
                quote_age_ms=float(age) if isinstance(age, int | float) else None,
                location=location,
                spread_ticks=spread,
                degraded=bool(row.get("trade_classification_degraded")),
                coalesced=bool(row.get("trade_coalesced")),
            )
        )
    collected.sort(key=lambda item: item.receive_ts_ns)
    return TradePrintSeries(
        prints=tuple(collected),
        timestamps=tuple(item.receive_ts_ns for item in collected),
        schema_packets=schema_packets,
        excluded_no_increment=no_increment,
        excluded_missing_classifier_version=missing_classifier,
        excluded_wrong_classifier_version=wrong_classifier,
        excluded_missing_alignment_version=missing_alignment,
        excluded_wrong_alignment_version=wrong_alignment,
        excluded_unusable_price=unusable_price,
        without_displayed_quote=without_quote,
    )


def spread_bucket_label(
    spread_ticks: float, edges: Sequence[float] = SPREAD_BUCKET_EDGES_TICKS
) -> str:
    """Half-open ``[lower, upper)`` bucket label; the final bucket is open above."""

    lower = 0.0
    for edge in edges:
        if spread_ticks < edge:
            return f"[{lower:g},{edge:g})"
        lower = edge
    return f"[{lower:g},inf)"


def _distribution(group: Sequence[TradePrint]) -> dict[str, Any]:
    counts = dict.fromkeys(PRINT_LOCATIONS, 0)
    for item in group:
        if item.location is not None:
            counts[item.location.value] += 1
    total = sum(counts.values())
    signed = sum(1 for item in group if item.signed and item.location is not None)
    degraded = sum(1 for item in group if item.degraded and item.location is not None)
    coalesced = sum(1 for item in group if item.coalesced and item.location is not None)
    return {
        "n": total,
        "counts": counts,
        "shares": {
            key: (value / total if total else None) for key, value in sorted(counts.items())
        },
        "inside_share": (counts[PrintLocation.STRICTLY_INSIDE.value] / total if total else None),
        "at_touch_share": (
            (counts[PrintLocation.AT_BID.value] + counts[PrintLocation.AT_ASK.value]) / total
            if total
            else None
        ),
        "outside_share": (counts[PrintLocation.STRICTLY_OUTSIDE.value] / total if total else None),
        "signed_prints": signed,
        "degraded_prints": degraded,
        "coalesced_prints": coalesced,
    }


def _quantiles(values: Sequence[float], probabilities: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {f"p{int(probability * 100)}": None for probability in probabilities}
    ordered = sorted(values)
    result: dict[str, float | None] = {}
    for probability in probabilities:
        position = probability * (len(ordered) - 1)
        low = int(position)
        high = min(low + 1, len(ordered) - 1)
        weight = position - low
        result[f"p{int(probability * 100)}"] = (
            ordered[low] * (1.0 - weight) + ordered[high] * weight
        )
    return result


def print_location_diagnostics(
    series: TradePrintSeries, *, edges: Sequence[float] = SPREAD_BUCKET_EDGES_TICKS
) -> dict[str, Any]:
    """`TOUCH-01`: the distribution of print locations overall, by hour and by spread bucket.

    This is the measurement that either confirms or refutes the `ID-CKS-02` finding of 42-48% of
    executions printing strictly inside the displayed quote.  It is reported as measured.
    """

    quoted = [item for item in series.prints if item.location is not None]
    by_hour: dict[str, Any] = {}
    for hour in sorted({item.ist_hour for item in quoted}):
        by_hour[f"{hour:02d}"] = _distribution([item for item in quoted if item.ist_hour == hour])
    by_bucket: dict[str, Any] = {}
    labelled = [
        (spread_bucket_label(float(item.spread_ticks), edges), item)
        for item in quoted
        if item.spread_ticks is not None
    ]
    for label in sorted({key for key, _ in labelled}):
        by_bucket[label] = _distribution([item for key, item in labelled if key == label])
    by_channel: dict[str, Any] = {}
    for channel in sorted({item.quote_channel or "unknown" for item in quoted}):
        by_channel[channel] = _distribution(
            [item for item in quoted if (item.quote_channel or "unknown") == channel]
        )
    spreads = [float(item.spread_ticks) for item in quoted if item.spread_ticks is not None]
    ages = [float(item.quote_age_ms) for item in quoted if item.quote_age_ms is not None]
    return {
        "requirement": "TOUCH-01",
        "specification_id": SPECIFICATION_ID,
        "definition": (
            "each observed positive-volume print is compared with the displayed level one the "
            "capture-time DAT-14 classifier aligned to it; comparison is on the quantised tick "
            "grid so binary32 Full prices and binary64 depth prices compare exactly"
        ),
        "overall": _distribution(quoted),
        "by_ist_hour": by_hour,
        "by_displayed_spread_bucket_ticks": by_bucket,
        "by_displayed_quote_channel": by_channel,
        "displayed_quote_age_ms": {
            "n": len(ages),
            "mean": (sum(ages) / len(ages)) if ages else None,
            **_quantiles(ages, (0.5, 0.9, 0.99)),
        },
        "displayed_spread_ticks": {
            "n": len(spreads),
            "mean": (sum(spreads) / len(spreads)) if spreads else None,
            **_quantiles(spreads, (0.1, 0.5, 0.9)),
        },
        "prints_without_displayed_quote": series.without_displayed_quote,
        "schema_packets": series.schema_packets,
        "excluded": {
            "no_volume_increment": series.excluded_no_increment,
            "missing_classifier_version": series.excluded_missing_classifier_version,
            "wrong_classifier_version": series.excluded_wrong_classifier_version,
            "missing_alignment_version": series.excluded_missing_alignment_version,
            "wrong_alignment_version": series.excluded_wrong_alignment_version,
            "unusable_price_or_timestamp": series.excluded_unusable_price,
        },
        "id_cks_02_reference": {
            "tape_a_inside_share": 0.481,
            "tape_b_inside_share": 0.419,
            "source": "research/docs/live-evidence/CKS-L1-OFI-SPEC-AMENDMENT-1-2026-08-19.md section A4",
        },
    }


@dataclass(frozen=True, slots=True)
class EffectiveTouch:
    """`TOUCH-02`: one estimated touch at one anchor, with its causal provenance."""

    window_seconds: float
    anchor_ts_ns: int
    effective_bid: float | None
    effective_ask: float | None
    buy_prints: int
    sell_prints: int
    newest_print_ts_ns: int | None
    crossed: bool

    @property
    def defined(self) -> bool:
        """A usable touch needs both bounds and must not be crossed."""

        return (
            self.effective_bid is not None and self.effective_ask is not None and not self.crossed
        )

    @property
    def mid(self) -> float | None:
        if not self.defined:
            return None
        assert self.effective_bid is not None and self.effective_ask is not None
        return (self.effective_bid + self.effective_ask) / 2.0

    @property
    def staleness_ns(self) -> int | None:
        """Age of the newest print that entered the estimate, in nanoseconds."""

        if self.newest_print_ts_ns is None:
            return None
        return self.anchor_ts_ns - self.newest_print_ts_ns

    @property
    def spread_ticks(self) -> float | None:
        if not self.defined:
            return None
        assert self.effective_bid is not None and self.effective_ask is not None
        return (self.effective_ask - self.effective_bid) / FUTURES_TICK_SIZE


class EffectiveTouchSeries:
    """`TOUCH-02`: the rolling causal effective-touch estimator over one tape's prints.

    Only prints with ``receive_ts_ns`` **strictly less than** the anchor are eligible, which is
    what `VAL-TOUCH-01` asserts.  A window with no buyer-initiated print, no seller-initiated
    print, or crossed bounds yields an undefined touch, and the caller must propagate it as
    missing — `VAL-TOUCH-02`.
    """

    __slots__ = ("_buy_prices", "_buy_ts", "_sell_prices", "_sell_ts", "_window_seconds")

    def __init__(self, prints: Sequence[TradePrint], *, window_seconds: float) -> None:
        if window_seconds <= 0:
            raise ValueError("the effective-touch window must be positive")
        self._window_seconds = float(window_seconds)
        buy_ts: list[int] = []
        buy_prices: list[float] = []
        sell_ts: list[int] = []
        sell_prices: list[float] = []
        for item in sorted(prints, key=lambda value: value.receive_ts_ns):
            if item.side == "buy":
                buy_ts.append(item.receive_ts_ns)
                buy_prices.append(item.price)
            elif item.side == "sell":
                sell_ts.append(item.receive_ts_ns)
                sell_prices.append(item.price)
        self._buy_ts = tuple(buy_ts)
        self._buy_prices = tuple(buy_prices)
        self._sell_ts = tuple(sell_ts)
        self._sell_prices = tuple(sell_prices)

    @property
    def window_seconds(self) -> float:
        return self._window_seconds

    @property
    def buy_prints(self) -> int:
        return len(self._buy_ts)

    @property
    def sell_prints(self) -> int:
        return len(self._sell_ts)

    def at(self, anchor_ts_ns: int) -> EffectiveTouch:
        """Estimate the touch from prints strictly inside ``(anchor - window, anchor)``."""

        start = anchor_ts_ns - int(self._window_seconds * NANOSECONDS_PER_SECOND)
        # bisect_left on the anchor keeps a print stamped exactly at the anchor out of the
        # window: the estimator may use the past only.
        buy_left = bisect_right(self._buy_ts, start)
        buy_right = bisect_left(self._buy_ts, anchor_ts_ns)
        sell_left = bisect_right(self._sell_ts, start)
        sell_right = bisect_left(self._sell_ts, anchor_ts_ns)
        buys = self._buy_prices[buy_left:buy_right]
        sells = self._sell_prices[sell_left:sell_right]
        effective_ask = min(buys) if buys else None
        effective_bid = max(sells) if sells else None
        newest: int | None = None
        if buy_right > buy_left:
            newest = self._buy_ts[buy_right - 1]
        if sell_right > sell_left:
            candidate = self._sell_ts[sell_right - 1]
            newest = candidate if newest is None else max(newest, candidate)
        crossed = (
            effective_bid is not None
            and effective_ask is not None
            and effective_bid >= effective_ask
        )
        return EffectiveTouch(
            window_seconds=self._window_seconds,
            anchor_ts_ns=anchor_ts_ns,
            effective_bid=effective_bid,
            effective_ask=effective_ask,
            buy_prints=len(buys),
            sell_prints=len(sells),
            newest_print_ts_ns=newest,
            crossed=crossed,
        )


def effective_touch_coverage(
    series: EffectiveTouchSeries, anchors: Sequence[int]
) -> dict[str, Any]:
    """`TOUCH-02`: per-anchor coverage and staleness for one declared window.

    Coverage is the share of anchors carrying a usable touch.  Staleness is the age of the newest
    print that entered the estimate; it is reported because the estimator is stale by
    construction between prints (`ID-TOUCH-01`).
    """

    total = len(anchors)
    defined = 0
    crossed = 0
    missing_buy = 0
    missing_sell = 0
    staleness: list[float] = []
    spreads: list[float] = []
    for anchor in anchors:
        touch = series.at(anchor)
        if touch.buy_prints == 0:
            missing_buy += 1
        if touch.sell_prints == 0:
            missing_sell += 1
        if touch.crossed:
            crossed += 1
        if touch.defined:
            defined += 1
            age = touch.staleness_ns
            if age is not None:
                staleness.append(age / NANOSECONDS_PER_SECOND)
            width = touch.spread_ticks
            if width is not None:
                spreads.append(width)
    return {
        "requirement": "TOUCH-02",
        "window_seconds": series.window_seconds,
        "anchors": total,
        "defined_anchors": defined,
        "coverage": (defined / total) if total else None,
        "anchors_without_buy_print": missing_buy,
        "anchors_without_sell_print": missing_sell,
        "crossed_anchors": crossed,
        "crossed_share": (crossed / total) if total else None,
        "staleness_seconds": {
            "n": len(staleness),
            "mean": (sum(staleness) / len(staleness)) if staleness else None,
            **_quantiles(staleness, (0.5, 0.9, 0.99)),
            "max": max(staleness) if staleness else None,
        },
        "effective_spread_ticks": {
            "n": len(spreads),
            "mean": (sum(spreads) / len(spreads)) if spreads else None,
            **_quantiles(spreads, (0.1, 0.5, 0.9)),
        },
        "undefined_is_missing_never_displayed_touch": True,
        "limitation_id": ID_TOUCH_01,
        "limitation": ID_TOUCH_01_LIMITATION,
    }


def effective_touch_metadata(
    *,
    windows: Sequence[float] = EFFECTIVE_TOUCH_WINDOWS_SECONDS,
    primary_window: float = PRIMARY_EFFECTIVE_TOUCH_WINDOW,
) -> dict[str, Any]:
    """The effective-touch block every artifact built on this estimator must carry."""

    return {
        "specification_id": SPECIFICATION_ID,
        "design_document": DESIGN_DOCUMENT,
        "estimator": "effective_touch_from_signed_prints",
        "definition": (
            "effective_ask <= min(buyer-initiated prints in (t-w, t)); "
            "effective_bid >= max(seller-initiated prints in (t-w, t))"
        ),
        "declared_windows_seconds": list(windows),
        "primary_window_seconds": primary_window,
        "causality": "strictly prior prints only; a print stamped at the anchor is excluded",
        "object_category": "proxy",
        "limitation_id": ID_TOUCH_01,
        "limitation": ID_TOUCH_01_LIMITATION,
    }
