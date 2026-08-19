"""SIG-21 outcome-blind construction of price-keyed far-book anomaly candidates.

This module deliberately has no response, return, label, matching, power or inference API.
It may be run before the H-SIG21 outcome gate because it consumes only consecutive depth200
states and past candidate magnitudes. See ``docs/sig-claims/H-SIG21.md``.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from shaurya.data.depth_thinning_analysis import DEPTH200, BookState

FAR_BOUNDARY_RUPEES = 20.0
DISTANCE_SPLIT_RUPEES = 50.0
RELOCATION_QUANTITY_TOLERANCE = 0.25
BOUNDARY_OVERLAP_RATIO = 0.95
BASELINE_THRESHOLDS = (0.995, 0.999)
MIN_BASELINE_EVENTS = 200

INVALID_QUALITY_FLAGS = frozenset(
    {
        "sequence_gap",
        "sequence_regression",
        "connection_gap",
        "reconnected",
        "heartbeat_timeout",
        "partial_book",
        "crossed_book",
        "invalid_depth",
    }
)

Side = Literal["bid", "ask"]


class AtomicEventType(StrEnum):
    ADDITION = "addition"
    REMOVAL = "removal"
    QUANTITY_INCREASE = "quantity_increase"
    QUANTITY_DECREASE = "quantity_decrease"
    ORDER_COUNT_INCREASE = "order_count_increase"
    ORDER_COUNT_DECREASE = "order_count_decrease"
    RELOCATION_TOWARD_TOUCH_PROXY = "relocation_toward_touch_proxy"
    RELOCATION_AWAY_FROM_TOUCH_PROXY = "relocation_away_from_touch_proxy"


@dataclass(frozen=True, slots=True)
class CandidateEvent:
    """One deterministic atomic event with no outcome fields."""

    instrument_id: str
    receive_ts_ns: int
    connection_epoch: int
    atomic_type: AtomicEventType
    side: Side
    price: float
    source_price: float | None
    distance_rupees: float
    distance_band: str
    magnitude: float
    quantity_before: int
    quantity_after: int
    orders_before: int
    orders_after: int
    object_category: Literal["deterministically_derived", "proxy"]

    def to_dict(self) -> dict[str, str | int | float | None]:
        return {
            "instrument_id": self.instrument_id,
            "receive_ts_ns": self.receive_ts_ns,
            "connection_epoch": self.connection_epoch,
            "atomic_type": str(self.atomic_type),
            "side": self.side,
            "price": self.price,
            "source_price": self.source_price,
            "distance_rupees": self.distance_rupees,
            "distance_band": self.distance_band,
            "magnitude": self.magnitude,
            "quantity_before": self.quantity_before,
            "quantity_after": self.quantity_after,
            "orders_before": self.orders_before,
            "orders_after": self.orders_after,
            "object_category": self.object_category,
        }


@dataclass(frozen=True, slots=True)
class Exclusion:
    reason: str
    side: Side | None = None
    prices: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class DetectionResult:
    candidates: tuple[CandidateEvent, ...]
    exclusions: tuple[Exclusion, ...]


@dataclass(frozen=True, slots=True)
class BaselineContext:
    """Past-only conditioning labels computed without any response information."""

    session_id: str
    session_start_ns: int
    time_bucket: str
    liquidity_bin: str
    regime: str


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    candidate: CandidateEvent
    history_n: int
    empirical_percentile: float | None
    thresholds_crossed: tuple[float, ...]
    status: Literal["baseline_insufficient", "scored"]


def _price_map(state: BookState, side: Side) -> dict[float, tuple[int, int]]:
    ladder = state.bids if side == "bid" else state.asks
    return {price: (quantity, orders) for price, quantity, orders in ladder}


def _best(state: BookState, side: Side) -> float | None:
    return state.best_bid if side == "bid" else state.best_ask


def _distance(best: float, price: float, side: Side) -> float:
    return best - price if side == "bid" else price - best


def _distance_band(distance: float) -> str:
    if distance <= DISTANCE_SPLIT_RUPEES:
        return "20_50"
    return "gt_50"


def _invalid_reason(previous: BookState, current: BookState) -> str | None:
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
    if previous.best_bid is None or previous.best_ask is None:
        return "missing_pre_event_best"
    if (
        previous.best_bid >= previous.best_ask
        or current.best_bid is None
        or current.best_ask is None
    ):
        return "crossed_pre_event_book"
    if current.best_bid >= current.best_ask:
        return "crossed_current_book"
    return None


def _boundary_churn(
    old: dict[float, tuple[int, int]],
    new: dict[float, tuple[int, int]],
    side: Side,
) -> tuple[set[float], set[float]]:
    """Return removed/added outer-boundary prices caused by a near-complete window slide."""
    removed = set(old) - set(new)
    added = set(new) - set(old)
    denominator = min(len(old), len(new))
    if not removed or not added or denominator == 0:
        return set(), set()
    overlap = len(set(old) & set(new)) / denominator
    if overlap < BOUNDARY_OVERLAP_RATIO or len(removed) > 2 or len(added) > 2:
        return set(), set()
    old_outer = min(old) if side == "bid" else max(old)
    new_outer = min(new) if side == "bid" else max(new)
    if old_outer not in removed or new_outer not in added:
        return set(), set()
    return removed, added


def _candidate(
    *,
    instrument_id: str,
    state: BookState,
    atomic_type: AtomicEventType,
    side: Side,
    price: float,
    source_price: float | None,
    best: float,
    magnitude: float,
    before: tuple[int, int],
    after: tuple[int, int],
    proxy: bool = False,
) -> CandidateEvent:
    distance_price = source_price if source_price is not None else price
    distance = _distance(best, distance_price, side)
    return CandidateEvent(
        instrument_id=instrument_id,
        receive_ts_ns=state.receive_ts_ns,
        connection_epoch=state.connection_epoch,
        atomic_type=atomic_type,
        side=side,
        price=price,
        source_price=source_price,
        distance_rupees=round(distance, 10),
        distance_band=_distance_band(distance),
        magnitude=float(magnitude),
        quantity_before=before[0],
        quantity_after=after[0],
        orders_before=before[1],
        orders_after=after[1],
        object_category="proxy" if proxy else "deterministically_derived",
    )


def _relocations(
    old: dict[float, tuple[int, int]],
    new: dict[float, tuple[int, int]],
    removed: set[float],
    added: set[float],
    side: Side,
    best: float,
    instrument_id: str,
    state: BookState,
) -> tuple[list[CandidateEvent], set[float], set[float]]:
    possible: list[tuple[float, float, float]] = []
    for source in removed:
        source_quantity = old[source][0]
        if source_quantity <= 0 or _distance(best, source, side) <= FAR_BOUNDARY_RUPEES:
            continue
        for destination in added:
            destination_quantity = new[destination][0]
            if (
                destination_quantity <= 0
                or _distance(best, destination, side) <= FAR_BOUNDARY_RUPEES
            ):
                continue
            relative_difference = abs(destination_quantity - source_quantity) / max(
                source_quantity, destination_quantity
            )
            if relative_difference <= RELOCATION_QUANTITY_TOLERANCE:
                possible.append((relative_difference, source, destination))
    used_removed: set[float] = set()
    used_added: set[float] = set()
    events: list[CandidateEvent] = []
    for _, source, destination in sorted(possible):
        if source in used_removed or destination in used_added:
            continue
        source_distance = _distance(best, source, side)
        destination_distance = _distance(best, destination, side)
        if destination_distance == source_distance:
            continue
        atomic_type = (
            AtomicEventType.RELOCATION_TOWARD_TOUCH_PROXY
            if destination_distance < source_distance
            else AtomicEventType.RELOCATION_AWAY_FROM_TOUCH_PROXY
        )
        before = old[source]
        after = new[destination]
        events.append(
            _candidate(
                instrument_id=instrument_id,
                state=state,
                atomic_type=atomic_type,
                side=side,
                price=destination,
                source_price=source,
                best=best,
                magnitude=min(before[0], after[0]),
                before=before,
                after=after,
                proxy=True,
            )
        )
        used_removed.add(source)
        used_added.add(destination)
    return events, used_removed, used_added


def detect_candidates(
    previous: BookState,
    current: BookState,
    *,
    instrument_id: str,
) -> DetectionResult:
    """Construct far-book candidates from one valid consecutive depth200 transition."""
    invalid = _invalid_reason(previous, current)
    if invalid is not None:
        return DetectionResult((), (Exclusion(invalid),))

    candidates: list[CandidateEvent] = []
    exclusions: list[Exclusion] = []
    for side in ("bid", "ask"):
        typed_side: Side = side
        best = _best(previous, typed_side)
        assert best is not None
        old = _price_map(previous, typed_side)
        new = _price_map(current, typed_side)
        removed = set(old) - set(new)
        added = set(new) - set(old)

        boundary_removed, boundary_added = _boundary_churn(old, new, typed_side)
        if boundary_removed or boundary_added:
            exclusions.append(
                Exclusion(
                    "whole_ladder_boundary_churn",
                    typed_side,
                    tuple(sorted(boundary_removed | boundary_added)),
                )
            )
            removed -= boundary_removed
            added -= boundary_added

        relocation_events, relocated_removed, relocated_added = _relocations(
            old,
            new,
            removed,
            added,
            typed_side,
            best,
            instrument_id,
            current,
        )
        candidates.extend(relocation_events)
        removed -= relocated_removed
        added -= relocated_added

        for price in sorted(removed):
            distance = _distance(best, price, typed_side)
            if distance <= FAR_BOUNDARY_RUPEES:
                continue
            before = old[price]
            candidates.append(
                _candidate(
                    instrument_id=instrument_id,
                    state=current,
                    atomic_type=AtomicEventType.REMOVAL,
                    side=typed_side,
                    price=price,
                    source_price=None,
                    best=best,
                    magnitude=before[0],
                    before=before,
                    after=(0, 0),
                )
            )
        for price in sorted(added):
            distance = _distance(best, price, typed_side)
            if distance <= FAR_BOUNDARY_RUPEES:
                continue
            after = new[price]
            candidates.append(
                _candidate(
                    instrument_id=instrument_id,
                    state=current,
                    atomic_type=AtomicEventType.ADDITION,
                    side=typed_side,
                    price=price,
                    source_price=None,
                    best=best,
                    magnitude=after[0],
                    before=(0, 0),
                    after=after,
                )
            )

        for price in sorted(set(old) & set(new)):
            distance = _distance(best, price, typed_side)
            if distance <= FAR_BOUNDARY_RUPEES:
                continue
            before = old[price]
            after = new[price]
            quantity_change = after[0] - before[0]
            if quantity_change:
                candidates.append(
                    _candidate(
                        instrument_id=instrument_id,
                        state=current,
                        atomic_type=(
                            AtomicEventType.QUANTITY_INCREASE
                            if quantity_change > 0
                            else AtomicEventType.QUANTITY_DECREASE
                        ),
                        side=typed_side,
                        price=price,
                        source_price=None,
                        best=best,
                        magnitude=abs(quantity_change),
                        before=before,
                        after=after,
                    )
                )
            order_change = after[1] - before[1]
            if order_change:
                candidates.append(
                    _candidate(
                        instrument_id=instrument_id,
                        state=current,
                        atomic_type=(
                            AtomicEventType.ORDER_COUNT_INCREASE
                            if order_change > 0
                            else AtomicEventType.ORDER_COUNT_DECREASE
                        ),
                        side=typed_side,
                        price=price,
                        source_price=None,
                        best=best,
                        magnitude=abs(order_change),
                        before=before,
                        after=after,
                    )
                )
    candidates.sort(key=lambda item: (item.side, str(item.atomic_type), item.price))
    return DetectionResult(tuple(candidates), tuple(exclusions))


class PreviousSessionEmpiricalBaseline:
    """Expanding empirical baseline which cannot learn from the session being scored."""

    def __init__(
        self,
        *,
        minimum_history: int = MIN_BASELINE_EVENTS,
        thresholds: tuple[float, ...] = BASELINE_THRESHOLDS,
    ) -> None:
        if minimum_history < 1:
            raise ValueError("minimum_history must be positive")
        if not thresholds or any(threshold <= 0.0 or threshold >= 1.0 for threshold in thresholds):
            raise ValueError("thresholds must lie strictly between zero and one")
        self.minimum_history = minimum_history
        self.thresholds = tuple(sorted(set(thresholds)))
        self._history: defaultdict[tuple[str, ...], list[float]] = defaultdict(list)
        self._pending: defaultdict[tuple[str, ...], list[float]] = defaultdict(list)
        self._session_id: str | None = None
        self._session_start_ns: int | None = None

    @staticmethod
    def _key(candidate: CandidateEvent, context: BaselineContext) -> tuple[str, ...]:
        return (
            str(candidate.atomic_type),
            candidate.side,
            candidate.distance_band,
            context.time_bucket,
            context.liquidity_bin,
            context.regime,
        )

    def _advance(self, context: BaselineContext) -> None:
        if self._session_id is None:
            self._session_id = context.session_id
            self._session_start_ns = context.session_start_ns
            return
        assert self._session_start_ns is not None
        if context.session_id == self._session_id:
            if context.session_start_ns != self._session_start_ns:
                raise ValueError("one session_id cannot have multiple start times")
            return
        if context.session_start_ns <= self._session_start_ns:
            raise ValueError("sessions must be scored in strictly increasing order")
        for key, values in self._pending.items():
            self._history[key].extend(values)
        self._pending.clear()
        self._session_id = context.session_id
        self._session_start_ns = context.session_start_ns

    def score(self, candidate: CandidateEvent, context: BaselineContext) -> ScoredCandidate:
        self._advance(context)
        key = self._key(candidate, context)
        history = self._history[key]
        history_n = len(history)
        percentile: float | None = None
        crossed: tuple[float, ...] = ()
        status: Literal["baseline_insufficient", "scored"] = "baseline_insufficient"
        if history_n >= self.minimum_history:
            ordered = sorted(history)
            percentile = bisect_right(ordered, candidate.magnitude) / history_n
            crossed = tuple(threshold for threshold in self.thresholds if percentile >= threshold)
            status = "scored"
        self._pending[key].append(candidate.magnitude)
        return ScoredCandidate(candidate, history_n, percentile, crossed, status)
