"""Causal high-frequency feature and target construction for Shaurya canonical data.

Every public identity in this module is versioned.  Missing inputs remain missing with an exact
reason; targets are returned through a separate type and cannot be serialized as input features.
All rolling helpers require one connection epoch and use only timestamps at or before the anchor.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum
from statistics import median, stdev
from types import MappingProxyType
from typing import Any, Final
from zoneinfo import ZoneInfo

import numpy as np
from scipy.optimize import minimize

from shaurya.contracts.tape import QualityFlag, TapeRow

from .option_pricing import (
    SECONDS_PER_YEAR,
    black76_price,
    essvi_static_arbitrage_passes,
    essvi_total_variance,
    implied_volatility,
)

FUTURES_TICK: Final = 0.05
STRIKE_STEP: Final = 50.0
EXATM_OFFSETS: Final = (-4, -3, -2, -1, 1, 2, 3, 4)
MAX_QUOTE_AGE_SECONDS: Final = 1.0
MIN_EXATM_PAIRS: Final = 5
ATM_IV_RATE: Final = 0.055
IST: Final = ZoneInfo("Asia/Kolkata")


class RelativeState(StrEnum):
    LOW = "low"
    MID = "mid"
    HIGH = "high"


class TrendState(StrEnum):
    CHOPPY = "choppy"
    MIXED = "mixed"
    TRENDING = "trending"


class ClockBucket(StrEnum):
    OPEN = "open"
    MORNING = "morning"
    MIDDAY = "midday"
    LATE = "late"
    CLOSE = "close"


@dataclass(frozen=True, slots=True)
class TimedValue:
    timestamp: datetime
    connection_epoch: int
    value: float | None

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        if self.connection_epoch < 1:
            raise ValueError("connection_epoch must be positive")
        if self.value is not None and not math.isfinite(self.value):
            raise ValueError("timed values must be finite or missing")


@dataclass(frozen=True, slots=True)
class OptionQuote:
    expiry: datetime
    strike: float
    is_call: bool
    bid: float
    ask: float
    receive_ts: datetime
    connection_epoch: int
    instrument_id: str = ""

    def __post_init__(self) -> None:
        if self.expiry.tzinfo is None or self.receive_ts.tzinfo is None:
            raise ValueError("option timestamps must be timezone-aware")
        if self.strike <= 0 or self.bid <= 0 or self.ask < self.bid:
            raise ValueError("option quote requires a positive, non-crossed BBO")
        if self.connection_epoch < 1:
            raise ValueError("connection_epoch must be positive")

    @property
    def mid(self) -> float:
        return 0.5 * (self.bid + self.ask)

    def age_seconds(self, anchor: datetime) -> float:
        return (anchor - self.receive_ts).total_seconds()


@dataclass(frozen=True, slots=True)
class VersionedValue:
    """One persisted derived value with semantic identity and causal lineage."""

    feature_version: str
    value: float | int | str | bool | None
    available_at: datetime | None
    source_timestamps: tuple[datetime, ...]
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.feature_version:
            raise ValueError("feature_version is required")
        if self.value is None:
            if not self.unavailable_reason or self.available_at is not None:
                raise ValueError("missing values require only an unavailable reason")
        else:
            if self.unavailable_reason is not None or self.available_at is None:
                raise ValueError("available values require an availability timestamp")
            if not self.source_timestamps:
                raise ValueError("available values require source timestamp lineage")
            if self.source_timestamps != tuple(sorted(set(self.source_timestamps))):
                raise ValueError("source timestamps must be sorted and unique")
            if self.available_at.tzinfo is None:
                raise ValueError("availability timestamp must be timezone-aware")
            if any(
                stamp.tzinfo is None or stamp > self.available_at
                for stamp in self.source_timestamps
            ):
                raise ValueError("source lineage cannot be naive or later than availability")

    @classmethod
    def missing(cls, feature_version: str, reason: str) -> VersionedValue:
        return cls(feature_version, None, None, (), reason)


@dataclass(frozen=True, slots=True)
class VersionedFeatureRow:
    decision_timestamp: datetime
    connection_epoch: int
    values: tuple[VersionedValue, ...]

    def __post_init__(self) -> None:
        if self.decision_timestamp.tzinfo is None:
            raise ValueError("decision_timestamp must be timezone-aware")
        versions = tuple(item.feature_version for item in self.values)
        if len(versions) != len(set(versions)):
            raise ValueError("feature row contains duplicate semantic identities")
        if versions != tuple(sorted(versions)):
            raise ValueError("feature row values must be sorted by feature-version identity")
        if any(
            item.available_at is not None and item.available_at > self.decision_timestamp
            for item in self.values
        ):
            raise ValueError("feature row contains future information")

    def to_dict(self) -> dict[str, Any]:
        """Serialize without ever dropping the exact feature-version identity."""

        return {
            "decision_timestamp": self.decision_timestamp.isoformat(),
            "connection_epoch": self.connection_epoch,
            "features": [
                {
                    "feature_version": item.feature_version,
                    "value": item.value,
                    "available_at": item.available_at.isoformat() if item.available_at else None,
                    "source_timestamps": [stamp.isoformat() for stamp in item.source_timestamps],
                    "unavailable_reason": item.unavailable_reason,
                }
                for item in self.values
            ],
        }


@dataclass(frozen=True, slots=True)
class TargetValue:
    """Future-only outcome type, deliberately incompatible with ``VersionedFeatureRow``."""

    target_version: str
    anchor_timestamp: datetime
    horizon_end: datetime
    connection_epoch: int
    value: float | None
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if self.anchor_timestamp.tzinfo is None or self.horizon_end.tzinfo is None:
            raise ValueError("target timestamps must be timezone-aware")
        if self.horizon_end <= self.anchor_timestamp:
            raise ValueError("target horizon must end after its anchor")
        if (self.value is None) == (self.unavailable_reason is None):
            raise ValueError("target must be either available or explicitly unavailable")
        if self.value is not None and not math.isfinite(self.value):
            raise ValueError("target value must be finite")


@dataclass(frozen=True, slots=True)
class ForwardConsensus:
    forward: float | None
    pairs: int
    dispersion: float | None
    strikes: tuple[float, ...]
    source_timestamps: tuple[datetime, ...]
    unavailable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ESSVIFit:
    theta: float | None
    rho: float | None
    psi: float | None
    converged: bool
    static_arbitrage_passed: bool
    usable_strikes: tuple[float, ...]
    unavailable_reason: str | None = None

    def total_variance(self, log_moneyness: float) -> float | None:
        if self.theta is None or self.rho is None or self.psi is None:
            return None
        return essvi_total_variance(log_moneyness, theta=self.theta, rho=self.rho, psi=self.psi)


def _valid_book(book: TapeRow, *, levels: int = 1) -> bool:
    invalid = {QualityFlag.CROSSED_BOOK, QualityFlag.INVALID_DEPTH, QualityFlag.STALE_QUOTE}
    return (
        not invalid.intersection(book.quality_flags)
        and len(book.bids) >= levels
        and len(book.asks) >= levels
        and book.best_bid is not None
        and book.best_ask is not None
        and book.best_ask >= book.best_bid
    )


def displayed_midpoint(book: TapeRow) -> float | None:
    if not _valid_book(book):
        return None
    assert book.best_bid is not None and book.best_ask is not None
    return 0.5 * (book.best_bid + book.best_ask)


def normalized_imbalance(bid_values: Sequence[float], ask_values: Sequence[float]) -> float | None:
    bid = float(sum(bid_values))
    ask = float(sum(ask_values))
    denominator = bid + ask
    return None if denominator <= 0 else (bid - ask) / denominator


def quantity_imbalance(book: TapeRow, *, levels: int) -> float | None:
    if not _valid_book(book, levels=levels):
        return None
    return normalized_imbalance(
        [level.quantity for level in book.bids[:levels]],
        [level.quantity for level in book.asks[:levels]],
    )


def order_count_imbalance(book: TapeRow, *, levels: int = 5) -> float | None:
    if not _valid_book(book, levels=levels):
        return None
    return normalized_imbalance(
        [level.orders for level in book.bids[:levels]],
        [level.orders for level in book.asks[:levels]],
    )


def inverse_depth_quantity_imbalance(book: TapeRow, *, levels: int = 5) -> float | None:
    if not _valid_book(book, levels=levels):
        return None
    weights = [1.0 / index for index in range(1, levels + 1)]
    return normalized_imbalance(
        [weight * level.quantity for weight, level in zip(weights, book.bids, strict=False)],
        [weight * level.quantity for weight, level in zip(weights, book.asks, strict=False)],
    )


def microprice_shift(book: TapeRow) -> float | None:
    if not _valid_book(book):
        return None
    bid = book.bids[0]
    ask = book.asks[0]
    denominator = bid.quantity + ask.quantity
    if denominator <= 0:
        return None
    midpoint = 0.5 * (bid.price + ask.price)
    microprice = (ask.price * bid.quantity + bid.price * ask.quantity) / denominator
    return microprice - midpoint


def futures_microprice_tilt_ticks(
    book: TapeRow, *, tick_size: float = FUTURES_TICK
) -> float | None:
    shift = microprice_shift(book)
    return None if shift is None else shift / tick_size


def l1_total_quantity(book: TapeRow) -> float | None:
    if not _valid_book(book):
        return None
    return float(book.bids[0].quantity + book.asks[0].quantity)


def log_l1_depth(book: TapeRow) -> float | None:
    depth = l1_total_quantity(book)
    return None if depth is None else math.log1p(depth)


def spread_ticks(book: TapeRow, *, tick_size: float = FUTURES_TICK) -> float | None:
    if not _valid_book(book):
        return None
    assert book.best_bid is not None and book.best_ask is not None
    return (book.best_ask - book.best_bid) / tick_size


def ccz_event_order_flow(
    previous: TapeRow, current: TapeRow, *, levels: int = 1
) -> tuple[float, ...] | None:
    """Exact Section-3 event flow, versioned separately from the legacy research constructor."""

    if (
        previous.connection_epoch != current.connection_epoch
        or not _valid_book(previous, levels=levels)
        or not _valid_book(current, levels=levels)
    ):
        return None
    result: list[float] = []
    for old_bid, new_bid, old_ask, new_ask in zip(
        previous.bids[:levels],
        current.bids[:levels],
        previous.asks[:levels],
        current.asks[:levels],
        strict=True,
    ):
        bid_flow = (
            float(new_bid.quantity)
            if new_bid.price > old_bid.price
            else float(new_bid.quantity - old_bid.quantity)
            if new_bid.price == old_bid.price
            else -float(old_bid.quantity)
        )
        ask_flow = (
            -float(new_ask.quantity)
            if new_ask.price > old_ask.price
            else float(new_ask.quantity - old_ask.quantity)
            if new_ask.price == old_ask.price
            else float(new_ask.quantity)
        )
        result.append(bid_flow - ask_flow)
    return tuple(result)


def ccz_average(
    states: Sequence[TapeRow], *, anchor: datetime, window_seconds: float = 0.5, levels: int = 1
) -> float | None:
    """Compute the common-depth-scaled average over ``(anchor-h, anchor]``."""

    if anchor.tzinfo is None or len(states) < 2:
        return None
    ordered = tuple(sorted(states, key=lambda row: (row.receive_ts, row.receive_sequence)))
    epoch = ordered[-1].connection_epoch
    start = anchor.timestamp() - window_seconds
    selected: list[tuple[tuple[float, ...], float]] = []
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if not start < current.receive_ts.timestamp() <= anchor.timestamp():
            continue
        if previous.connection_epoch != epoch or current.connection_epoch != epoch:
            return None
        flow = ccz_event_order_flow(previous, current, levels=levels)
        if flow is None:
            return None
        depth = sum(level.quantity for level in (*current.bids[:levels], *current.asks[:levels]))
        selected.append((flow, float(depth)))
    if not selected:
        return None
    events = len(selected)
    denominator = sum(depth for _, depth in selected) / (2.0 * levels * events)
    if denominator <= 0:
        return None
    raw = [sum(flow[level] for flow, _ in selected) for level in range(levels)]
    return sum(value / denominator for value in raw) / levels


def atm_strike(futures_mid: float, *, step: float = STRIKE_STEP) -> float:
    """Nearest strike with deterministic half-up tie handling."""

    if futures_mid <= 0 or step <= 0:
        raise ValueError("futures_mid and strike step must be positive")
    return step * math.floor(futures_mid / step + 0.5)


def exatm_forward_consensus(
    *,
    futures_mid: float,
    option_quotes: Sequence[OptionQuote],
    anchor: datetime,
    expiry: datetime,
    connection_epoch: int,
) -> ForwardConsensus:
    if anchor.tzinfo is None or expiry.tzinfo is None:
        raise ValueError("anchor and expiry must be timezone-aware")
    strike0 = atm_strike(futures_mid)
    latest: dict[tuple[float, bool], OptionQuote] = {}
    for quote in option_quotes:
        if quote.expiry != expiry or quote.connection_epoch != connection_epoch:
            continue
        age = quote.age_seconds(anchor)
        if age < 0 or age > MAX_QUOTE_AGE_SECONDS:
            continue
        key = (quote.strike, quote.is_call)
        incumbent = latest.get(key)
        if incumbent is None or quote.receive_ts > incumbent.receive_ts:
            latest[key] = quote
    values: list[tuple[float, float, tuple[datetime, datetime]]] = []
    for offset in EXATM_OFFSETS:
        strike = strike0 + STRIKE_STEP * offset
        call = latest.get((strike, True))
        put = latest.get((strike, False))
        if call is None or put is None:
            continue
        values.append((strike, strike + call.mid - put.mid, (call.receive_ts, put.receive_ts)))
    if len(values) < MIN_EXATM_PAIRS:
        return ForwardConsensus(
            None,
            len(values),
            None,
            tuple(item[0] for item in values),
            (),
            "fewer_than_five_fresh_exatm_pairs",
        )
    forwards = [item[1] for item in values]
    return ForwardConsensus(
        float(median(forwards)),
        len(values),
        max(forwards) - min(forwards),
        tuple(item[0] for item in values),
        tuple(sorted({stamp for item in values for stamp in item[2]})),
    )


def basis_raw(futures_mid: float | None, exatm_forward: float | None) -> float | None:
    return None if futures_mid is None or exatm_forward is None else futures_mid - exatm_forward


def lagged_median_basis(
    history: Sequence[TimedValue], *, anchor: datetime, connection_epoch: int
) -> float | None:
    """Lag-1 rolling 30-second median with ten-observation minimum."""

    lower = anchor.timestamp() - 30.0
    values = [
        item.value
        for item in history
        if item.connection_epoch == connection_epoch
        and lower <= item.timestamp.timestamp() < anchor.timestamp()
        and item.value is not None
    ]
    return None if len(values) < 10 else float(median(values[-30:]))


def parity_pressure(raw_basis: float | None, slow_basis: float | None) -> float | None:
    return None if raw_basis is None or slow_basis is None else -(raw_basis - slow_basis)


def fair_quality(pressure: float | None, dispersion: float | None) -> float | None:
    return None if pressure is None or dispersion is None else pressure / (dispersion + 0.25)


def sign_agreement(
    left: float | None, right: float | None, *, require_nonzero: bool = False
) -> float | None:
    if left is None or right is None:
        return None
    if require_nonzero and (left == 0 or right == 0):
        return 0.0
    return float(np.sign(left) == np.sign(right))


def convergence(pressure: float | None, future_move_ticks: float | None) -> float | None:
    return (
        None
        if pressure is None or future_move_ticks is None
        else float(np.sign(pressure)) * future_move_ticks
    )


def aligned_post_fill(value: float | None, *, bid_buy: bool, is_call: bool) -> float | None:
    if value is None:
        return None
    return direction_alignment(bid_buy=bid_buy, is_call=is_call) * value


def direction_alignment(*, bid_buy: bool, is_call: bool) -> float:
    position_sign = 1.0 if bid_buy else -1.0
    delta_sign = 1.0 if is_call else -1.0
    return position_sign * delta_sign


def _point_map(points: Sequence[TimedValue]) -> Mapping[tuple[int, datetime], float | None]:
    return MappingProxyType(
        {(item.connection_epoch, item.timestamp): item.value for item in points}
    )


def prior_move_ticks(
    points: Sequence[TimedValue],
    *,
    anchor: datetime,
    connection_epoch: int,
    seconds: int = 5,
    tick_size: float = FUTURES_TICK,
) -> float | None:
    values = _point_map(points)
    current = values.get((connection_epoch, anchor))
    prior = values.get((connection_epoch, anchor - timedelta(seconds=seconds)))
    return None if current is None or prior is None else (current - prior) / tick_size


def midpoint_volatility(
    points: Sequence[TimedValue], *, anchor: datetime, connection_epoch: int, seconds: int
) -> float | None:
    values = _point_map(points)
    mids: list[float] = []
    for offset in range(seconds, -1, -1):
        stamp = anchor - timedelta(seconds=offset)
        value = values.get((connection_epoch, stamp))
        if value is None:
            return None
        mids.append(value)
    changes = [right - left for left, right in zip(mids, mids[1:], strict=False)]
    mean = sum(changes) / len(changes)
    return math.sqrt(sum((item - mean) ** 2 for item in changes) / len(changes))


def trend_efficiency(
    points: Sequence[TimedValue], *, anchor: datetime, connection_epoch: int
) -> float | None:
    values = _point_map(points)
    mids: list[float] = []
    for offset in range(10, -1, -1):
        stamp = anchor - timedelta(seconds=offset)
        value = values.get((connection_epoch, stamp))
        if value is None:
            return None
        mids.append(value)
    denominator = sum(abs(right - left) for left, right in zip(mids, mids[1:], strict=False))
    return None if denominator == 0 else abs(mids[-1] - mids[0]) / denominator


def trend_state(value: float | None) -> TrendState | None:
    if value is None:
        return None
    if value <= 0.30:
        return TrendState.CHOPPY
    if value >= 0.65:
        return TrendState.TRENDING
    return TrendState.MIXED


def _linear_quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def relative_tertile_state(
    current: TimedValue,
    history: Sequence[TimedValue],
    *,
    window_seconds: int = 900,
    minimum_observations: int = 120,
) -> tuple[RelativeState | None, float | None, float | None]:
    lower = current.timestamp.timestamp() - window_seconds
    values = [
        item.value
        for item in history
        if item.connection_epoch == current.connection_epoch
        and lower <= item.timestamp.timestamp() < current.timestamp.timestamp()
        and item.value is not None
    ]
    if current.value is None or len(values) < minimum_observations:
        return None, None, None
    q33 = _linear_quantile(values, 0.33)
    q67 = _linear_quantile(values, 0.67)
    state = (
        RelativeState.LOW
        if current.value < q33
        else RelativeState.HIGH
        if current.value > q67
        else RelativeState.MID
    )
    return state, q33, q67


def ist_clock_bucket(timestamp: datetime) -> ClockBucket | None:
    local = timestamp.astimezone(IST).timetz().replace(tzinfo=None)
    if time(9, 15) <= local < time(10):
        return ClockBucket.OPEN
    if time(10) <= local < time(12):
        return ClockBucket.MORNING
    if time(12) <= local < time(14):
        return ClockBucket.MIDDAY
    if time(14) <= local < time(15):
        return ClockBucket.LATE
    if time(15) <= local <= time(15, 30):
        return ClockBucket.CLOSE
    return None


def calendar_dte(anchor: datetime, expiry: datetime) -> int | None:
    """Calendar days to expiry, retained only as support metadata."""

    if anchor.tzinfo is None or expiry.tzinfo is None or expiry < anchor:
        return None
    return (expiry.astimezone(IST).date() - anchor.astimezone(IST).date()).days


def fit_essvi_equal_weight(
    log_moneyness: Sequence[float], total_variances: Sequence[float], *, strikes: Sequence[float]
) -> ESSVIFit:
    if len(log_moneyness) != len(total_variances) or len(strikes) != len(total_variances):
        raise ValueError("eSSVI inputs must have equal lengths")
    if len(total_variances) < MIN_EXATM_PAIRS:
        return ESSVIFit(
            None, None, None, False, False, tuple(strikes), "fewer_than_five_usable_strikes"
        )
    x = np.asarray(log_moneyness, dtype=np.float64)
    y = np.asarray(total_variances, dtype=np.float64)
    if np.any(~np.isfinite(x)) or np.any(~np.isfinite(y)) or np.any(y <= 0):
        return ESSVIFit(
            None, None, None, False, False, tuple(strikes), "invalid_total_variance_inputs"
        )

    def objective(params: np.ndarray[Any, np.dtype[np.float64]]) -> float:
        theta, rho, psi = (float(item) for item in params)
        model = np.asarray(
            [essvi_total_variance(float(item), theta=theta, rho=rho, psi=psi) for item in x]
        )
        return float(np.mean((model - y) ** 2))

    theta0 = max(float(np.median(y)), 1e-6)
    result: Any = minimize(
        objective,
        np.asarray([theta0, -0.3, min(0.1, math.sqrt(2.0 * theta0))]),
        method="L-BFGS-B",
        bounds=((1e-10, 5.0), (-0.999, 0.999), (1e-10, 4.0)),
        options={"maxiter": 2_000, "ftol": 1e-15},
    )
    if not bool(result.success):
        return ESSVIFit(
            None, None, None, False, False, tuple(strikes), f"optimizer_failed:{result.message}"
        )
    theta, rho, psi = (float(item) for item in result.x)
    passed = essvi_static_arbitrage_passes(theta=theta, rho=rho, psi=psi)
    if not passed:
        return ESSVIFit(None, None, None, True, False, tuple(strikes), "static_arbitrage_failed")
    return ESSVIFit(theta, rho, psi, True, True, tuple(strikes))


def _group_quotes(quotes: Iterable[OptionQuote]) -> dict[tuple[float, bool], list[OptionQuote]]:
    grouped: dict[tuple[float, bool], list[OptionQuote]] = {}
    for quote in quotes:
        grouped.setdefault((quote.strike, quote.is_call), []).append(quote)
    return grouped


def fit_leave_atm_essvi_v2(
    *,
    futures_mid: float,
    option_quotes: Sequence[OptionQuote],
    anchor: datetime,
    expiry: datetime,
    connection_epoch: int,
    risk_free_rate: float = ATM_IV_RATE,
) -> tuple[ForwardConsensus, ESSVIFit]:
    consensus = exatm_forward_consensus(
        futures_mid=futures_mid,
        option_quotes=option_quotes,
        anchor=anchor,
        expiry=expiry,
        connection_epoch=connection_epoch,
    )
    if consensus.forward is None:
        return consensus, ESSVIFit(
            None, None, None, False, False, consensus.strikes, consensus.unavailable_reason
        )
    maturity = (expiry - anchor).total_seconds() / SECONDS_PER_YEAR
    if maturity <= 0:
        return consensus, ESSVIFit(
            None, None, None, False, False, consensus.strikes, "expired_contract"
        )
    latest = {
        key: max(rows, key=lambda quote: quote.receive_ts)
        for key, rows in _group_quotes(
            quote
            for quote in option_quotes
            if quote.expiry == expiry
            and quote.connection_epoch == connection_epoch
            and 0 <= quote.age_seconds(anchor) <= MAX_QUOTE_AGE_SECONDS
        ).items()
    }
    strikes: list[float] = []
    log_moneyness: list[float] = []
    variances: list[float] = []
    for strike in consensus.strikes:
        is_call = strike >= consensus.forward
        quote = latest.get((strike, is_call))
        if quote is None:
            continue
        volatility = implied_volatility(
            price=quote.mid,
            forward=consensus.forward,
            strike=strike,
            maturity_years=maturity,
            risk_free_rate=risk_free_rate,
            is_call=is_call,
        )
        if volatility is None:
            continue
        strikes.append(strike)
        log_moneyness.append(math.log(strike / consensus.forward))
        variances.append(volatility**2 * maturity)
    return consensus, fit_essvi_equal_weight(log_moneyness, variances, strikes=strikes)


def surface_residual_v2(
    *,
    fit: ESSVIFit,
    forward: float,
    strike: float,
    maturity_years: float,
    observed_mid: float,
    is_call: bool,
    risk_free_rate: float = ATM_IV_RATE,
) -> float | None:
    total_variance = fit.total_variance(math.log(strike / forward))
    if total_variance is None or maturity_years <= 0:
        return None
    fair = black76_price(
        forward=forward,
        strike=strike,
        maturity_years=maturity_years,
        volatility=math.sqrt(total_variance / maturity_years),
        risk_free_rate=risk_free_rate,
        is_call=is_call,
    )
    return fair - observed_mid


def atm_implied_volatility_state(
    *,
    futures_mid: float,
    option_quotes: Sequence[OptionQuote],
    anchor: datetime,
    expiry: datetime,
    connection_epoch: int,
    futures_receive_ts: datetime,
    risk_free_rate: float = ATM_IV_RATE,
) -> tuple[float | None, float | None, float | None, str | None]:
    consensus = exatm_forward_consensus(
        futures_mid=futures_mid,
        option_quotes=option_quotes,
        anchor=anchor,
        expiry=expiry,
        connection_epoch=connection_epoch,
    )
    if consensus.forward is None or consensus.dispersion is None:
        return None, None, None, consensus.unavailable_reason
    if consensus.dispersion > 5.0:
        return None, None, None, "range_exatm_above_5"
    if not 0 <= (anchor - futures_receive_ts).total_seconds() <= MAX_QUOTE_AGE_SECONDS:
        return None, None, None, "stale_futures_input"
    strike = atm_strike(futures_mid)
    candidates = [
        quote
        for quote in option_quotes
        if quote.expiry == expiry
        and quote.strike == strike
        and quote.connection_epoch == connection_epoch
        and 0 <= quote.age_seconds(anchor) <= MAX_QUOTE_AGE_SECONDS
    ]
    call = max(
        (quote for quote in candidates if quote.is_call),
        key=lambda item: item.receive_ts,
        default=None,
    )
    put = max(
        (quote for quote in candidates if not quote.is_call),
        key=lambda item: item.receive_ts,
        default=None,
    )
    if call is None or put is None:
        return None, None, None, "missing_or_stale_atm_pair"
    maturity = (expiry - anchor).total_seconds() / SECONDS_PER_YEAR
    call_iv = implied_volatility(
        price=call.mid,
        forward=consensus.forward,
        strike=strike,
        maturity_years=maturity,
        risk_free_rate=risk_free_rate,
        is_call=True,
    )
    put_iv = implied_volatility(
        price=put.mid,
        forward=consensus.forward,
        strike=strike,
        maturity_years=maturity,
        risk_free_rate=risk_free_rate,
        is_call=False,
    )
    if call_iv is None or put_iv is None:
        return None, None, None, "implied_volatility_inversion_failed"
    return call_iv, put_iv, 0.5 * (call_iv + put_iv), None


def iv_shock_bp(
    points: Sequence[TimedValue], *, anchor: datetime, connection_epoch: int, seconds: int
) -> float | None:
    move = prior_move_ticks(
        points, anchor=anchor, connection_epoch=connection_epoch, seconds=seconds, tick_size=0.0001
    )
    return move


def iv_change_target(
    points: Sequence[TimedValue],
    *,
    anchor: datetime,
    connection_epoch: int,
    horizon_seconds: int,
) -> TargetValue:
    """Future ATM-IV change in basis points, kept outside the feature namespace."""

    end = anchor + timedelta(seconds=horizon_seconds)
    values = _point_map(points)
    current = values.get((connection_epoch, anchor))
    future = values.get((connection_epoch, end))
    value = None if current is None or future is None else 10_000.0 * (future - current)
    return TargetValue(
        f"target.option.atm_iv_change_{horizon_seconds}s_bp.v1",
        anchor,
        end,
        connection_epoch,
        value,
        None if value is not None else "missing_same_epoch_endpoint",
    )


def iv_vol_of_vol_60s(
    shocks: Sequence[TimedValue], *, anchor: datetime, connection_epoch: int
) -> float | None:
    lower = anchor.timestamp() - 59.0
    values = [
        item.value
        for item in shocks
        if item.connection_epoch == connection_epoch
        and lower <= item.timestamp.timestamp() <= anchor.timestamp()
        and item.value is not None
    ]
    return None if len(values) < 40 else stdev(values)


def future_mid_move_target(
    points: Sequence[TimedValue],
    *,
    anchor: datetime,
    connection_epoch: int,
    horizon_seconds: int,
    tick_size: float = FUTURES_TICK,
) -> TargetValue:
    end = anchor + timedelta(seconds=horizon_seconds)
    values = _point_map(points)
    current = values.get((connection_epoch, anchor))
    future = values.get((connection_epoch, end))
    value = None if current is None or future is None else (future - current) / tick_size
    return TargetValue(
        f"target.futures.mid_move_ticks_{horizon_seconds}s.v1",
        anchor,
        end,
        connection_epoch,
        value,
        None if value is not None else "missing_same_epoch_endpoint",
    )


def future_range_target(
    points: Sequence[TimedValue],
    *,
    anchor: datetime,
    connection_epoch: int,
    horizon_seconds: int,
    tick_size: float = FUTURES_TICK,
) -> TargetValue:
    end = anchor + timedelta(seconds=horizon_seconds)
    values = _point_map(points)
    path: list[float] = []
    for offset in range(horizon_seconds + 1):
        stamp = anchor + timedelta(seconds=offset)
        value = values.get((connection_epoch, stamp))
        if value is None:
            return TargetValue(
                f"target.futures.range_ticks_{horizon_seconds}s.v1",
                anchor,
                end,
                connection_epoch,
                None,
                "incomplete_same_epoch_horizon",
            )
        path.append(value)
    return TargetValue(
        f"target.futures.range_ticks_{horizon_seconds}s.v1",
        anchor,
        end,
        connection_epoch,
        (max(path) - min(path)) / tick_size,
    )


def raw_option_markout(current_mid: float | None, future_mid: float | None) -> float | None:
    return None if current_mid is None or future_mid is None else future_mid - current_mid


def actual_futures_hedged_markout(
    *,
    current_option_mid: float | None,
    future_option_mid: float | None,
    beta: float | None,
    current_futures_mid: float | None,
    future_futures_mid: float | None,
) -> float | None:
    if None in (
        current_option_mid,
        future_option_mid,
        beta,
        current_futures_mid,
        future_futures_mid,
    ):
        return None
    assert current_option_mid is not None and future_option_mid is not None
    assert beta is not None and current_futures_mid is not None and future_futures_mid is not None
    return (future_option_mid - current_option_mid) - beta * (
        future_futures_mid - current_futures_mid
    )


def spread_change_target(
    current_spread_ticks: float | None, future_spread_ticks: float | None
) -> float | None:
    return (
        None
        if current_spread_ticks is None or future_spread_ticks is None
        else future_spread_ticks - current_spread_ticks
    )


def surface_residual_difference(
    call_residual: float | None, put_residual: float | None
) -> float | None:
    return None if call_residual is None or put_residual is None else call_residual - put_residual


def atm_cp_iv_difference_bp(call_iv: float | None, put_iv: float | None) -> float | None:
    return None if call_iv is None or put_iv is None else 10_000.0 * (call_iv - put_iv)


def atm_surface_gap_bp(
    atm_iv: float | None,
    *,
    fit: ESSVIFit,
    forward: float,
    strike: float,
    maturity_years: float,
) -> float | None:
    total_variance = fit.total_variance(math.log(strike / forward))
    if atm_iv is None or total_variance is None or maturity_years <= 0:
        return None
    surface_iv = math.sqrt(total_variance / maturity_years)
    return 10_000.0 * (atm_iv - surface_iv)


def reversal_pressure_5s(prior_move_5s_ticks: float | None) -> float | None:
    return None if prior_move_5s_ticks is None else -prior_move_5s_ticks


def parity_highvol_tightspread_gate(
    volatility: RelativeState | None, spread: RelativeState | None
) -> bool | None:
    if volatility is None or spread is None:
        return None
    return volatility is RelativeState.HIGH and spread is RelativeState.LOW


def order_count_large_midday_gate(
    strength: RelativeState | None, bucket: ClockBucket | None
) -> bool | None:
    if strength is None or bucket is None:
        return None
    return strength is RelativeState.HIGH and bucket is ClockBucket.MIDDAY


def l1_quantity_lowvol_middepth_gate(
    volatility: RelativeState | None, depth: RelativeState | None
) -> bool | None:
    if volatility is None or depth is None:
        return None
    return volatility is RelativeState.LOW and depth is RelativeState.MID


def microprice_large_close_gate(
    strength: RelativeState | None, bucket: ClockBucket | None
) -> bool | None:
    if strength is None or bucket is None:
        return None
    return strength is RelativeState.HIGH and bucket is ClockBucket.CLOSE


def reversal_large_move_mid_parity_dispersion_gate(
    strength: RelativeState | None, parity_noise: RelativeState | None
) -> bool | None:
    if strength is None or parity_noise is None:
        return None
    return strength is RelativeState.HIGH and parity_noise is RelativeState.MID


def surface_diff_large_noisy_parity_gate(
    strength: RelativeState | None, parity_noise: RelativeState | None
) -> bool | None:
    if strength is None or parity_noise is None:
        return None
    return strength is RelativeState.HIGH and parity_noise is RelativeState.HIGH


def own_ce_surface_noisy_choppy_gate(
    parity_noise: RelativeState | None, trend: TrendState | None
) -> bool | None:
    if parity_noise is None or trend is None:
        return None
    return parity_noise is RelativeState.HIGH and trend is TrendState.CHOPPY


def own_pe_surface_noisy_midvol_gate(
    parity_noise: RelativeState | None, volatility: RelativeState | None
) -> bool | None:
    if parity_noise is None or volatility is None:
        return None
    return parity_noise is RelativeState.HIGH and volatility is RelativeState.MID


def fast_ofi_lowvol_trending_gate(
    volatility: RelativeState | None, trend: TrendState | None
) -> bool | None:
    if volatility is None or trend is None:
        return None
    return volatility is RelativeState.LOW and trend is TrendState.TRENDING


def atm_iv_reversal_mid_vov_gate(state: RelativeState | None) -> bool | None:
    return None if state is None else state is RelativeState.MID


def gate_all(*conditions: bool | None) -> bool | None:
    return (
        None if any(item is None for item in conditions) else all(bool(item) for item in conditions)
    )
