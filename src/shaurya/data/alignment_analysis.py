"""DAT-15 cross-channel alignment and coalesced-print measurement.

The causal quote age is observed from DAT-14's selected pre-print quote.  A classification
"flip" is a diagnostic proxy: the recorded side is compared with the side obtained from the
first complete same-tier depth BBO received after the print, within a fixed horizon.  Dhan deep
packets have no exchange timestamp, so this post-print BBO is not identified as the true quote at
the exchange when the trade occurred.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from shaurya.contracts.tape import QualityFlag, TapeRow, TradeSide
from shaurya.contracts.timing import IST
from shaurya.data.tape import JsonlTapeReader
from shaurya.data.trade_direction import CaptureTradeDirectionClassifier, classify_trade


@dataclass(frozen=True, slots=True)
class _DepthQuote:
    instrument_id: str
    channel: str
    receive_ts: datetime
    best_bid: float
    best_ask: float


@dataclass(slots=True)
class _PriceState:
    last: float | None = None
    prior_differing: float | None = None

    def before(self, price: float) -> float | None:
        if self.last is None:
            return None
        return self.last if price != self.last else self.prior_differing

    def observe(self, price: float) -> None:
        if self.last is None:
            self.last = price
        elif price != self.last:
            self.prior_differing = self.last
            self.last = price


@dataclass(frozen=True, slots=True)
class AlignmentObservation:
    tape: str
    instrument_id: str
    receive_ts: datetime
    activity_rate_per_minute: float
    activity_band: str
    depth_tier: str
    quote_age_ms: float | None
    recorded_side: TradeSide
    recorded_reason: str
    degraded: bool
    cumulative_volume_increment: int
    last_quantity: int
    coalesced: bool
    post_quote_delay_ms: float | None
    post_proxy_side: TradeSide | None

    @property
    def directional_pair(self) -> bool:
        return self.recorded_side in {TradeSide.BUY, TradeSide.SELL} and self.post_proxy_side in {
            TradeSide.BUY,
            TradeSide.SELL,
        }

    @property
    def flipped(self) -> bool | None:
        if not self.directional_pair:
            return None
        return self.recorded_side is not self.post_proxy_side

    @property
    def time_bucket(self) -> str:
        hour = self.receive_ts.astimezone(IST).hour
        if hour < 12:
            return "morning_before_12"
        if hour < 14:
            return "midday_12_to_14"
        return "afternoon_after_14"

    @property
    def quote_age_band(self) -> str:
        if self.quote_age_ms is None:
            return "missing"
        if self.quote_age_ms <= 100:
            return "le_100ms"
        if self.quote_age_ms <= 250:
            return "gt_100_le_250ms"
        if self.quote_age_ms <= 500:
            return "gt_250_le_500ms"
        return "gt_500ms"


@dataclass(frozen=True, slots=True)
class TapeCoverage:
    path: str
    rows: int
    positive_volume_prints: int
    print_rate_per_minute: float
    activity_band: str
    instrument_ids: tuple[str, ...]
    depth_tiers: tuple[str, ...]
    started_at: str | None
    finished_at: str | None


def _activity_band(rate: float) -> str:
    if rate < 5:
        return "quiet_lt_5_prints_per_min"
    if rate < 15:
        return "moderate_5_to_15_prints_per_min"
    return "active_ge_15_prints_per_min"


def _quantiles(values: Iterable[float]) -> dict[str, float | int | None]:
    ordered = sorted(values)
    if not ordered:
        return {
            "n": 0,
            "min": None,
            "p05": None,
            "p25": None,
            "p50": None,
            "p75": None,
            "p95": None,
            "p99": None,
            "max": None,
        }

    def at(probability: float) -> float:
        return ordered[round((len(ordered) - 1) * probability)]

    return {
        "n": len(ordered),
        "min": ordered[0],
        "p05": at(0.05),
        "p25": at(0.25),
        "p50": at(0.50),
        "p75": at(0.75),
        "p95": at(0.95),
        "p99": at(0.99),
        "max": ordered[-1],
    }


def _complete_depth_quotes(rows: Sequence[TapeRow]) -> dict[tuple[str, str], list[_DepthQuote]]:
    side_times: dict[tuple[str, str, int], dict[str, datetime]] = defaultdict(dict)
    result: dict[tuple[str, str], list[_DepthQuote]] = defaultdict(list)
    for row in rows:
        if row.event_type not in {"depth20", "depth200"} or row.update_side not in {"bid", "ask"}:
            continue
        key = (row.instrument_id, row.event_type, row.connection_epoch)
        reconnect_flags = (QualityFlag.CONNECTION_GAP, QualityFlag.RECONNECTED)
        if any(flag in row.quality_flags for flag in reconnect_flags):
            side_times[key].clear()
        side_times[key][row.update_side] = row.receive_ts
        times = side_times[key]
        if not row.bids or not row.asks or "bid" not in times or "ask" not in times:
            continue
        result[(row.instrument_id, row.event_type)].append(
            _DepthQuote(
                row.instrument_id,
                row.event_type,
                max(times["bid"], times["ask"]),
                row.bids[0].price,
                row.asks[0].price,
            )
        )
    return result


def _first_post_quote(
    quotes: Sequence[_DepthQuote], print_ts: datetime, horizon_ms: float
) -> _DepthQuote | None:
    for quote in quotes:
        delay_ms = (quote.receive_ts - print_ts).total_seconds() * 1000
        if delay_ms <= 0:
            continue
        if delay_ms > horizon_ms:
            return None
        return quote
    return None


def _summarize(observations: Sequence[AlignmentObservation]) -> dict[str, Any]:
    quote_ages = [value.quote_age_ms for value in observations if value.quote_age_ms is not None]
    post_delays = [
        value.post_quote_delay_ms for value in observations if value.post_quote_delay_ms is not None
    ]
    directional = [value for value in observations if value.directional_pair]
    flips = sum(value.flipped is True for value in directional)
    coalesced = [value for value in observations if value.coalesced]
    excess = [value.cumulative_volume_increment - value.last_quantity for value in coalesced]
    increment_volume = sum(value.cumulative_volume_increment for value in observations)
    last_quantity_volume = sum(value.last_quantity for value in observations)
    return {
        "prints": len(observations),
        "side_counts": dict(Counter(value.recorded_side.value for value in observations)),
        "reason_counts": dict(Counter(value.recorded_reason for value in observations)),
        "degraded_count": sum(value.degraded for value in observations),
        "degraded_rate": (
            sum(value.degraded for value in observations) / len(observations)
            if observations
            else None
        ),
        "quote_age_ms": _quantiles(value for value in quote_ages if value is not None),
        "post_quote_delay_ms": _quantiles(value for value in post_delays if value is not None),
        "post_proxy_available": sum(value.post_proxy_side is not None for value in observations),
        "directional_comparisons": len(directional),
        "proxy_flip_count": flips,
        "proxy_flip_rate": flips / len(directional) if directional else None,
        "coalesced_count": len(coalesced),
        "coalesced_rate": len(coalesced) / len(observations) if observations else None,
        "coalesced_excess_units": _quantiles(float(value) for value in excess),
        "increment_volume": increment_volume,
        "last_quantity_volume": last_quantity_volume,
        "last_quantity_volume_coverage": (
            last_quantity_volume / increment_volume if increment_volume else None
        ),
    }


def _grouped(observations: Sequence[AlignmentObservation], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[AlignmentObservation]] = defaultdict(list)
    for value in observations:
        group = str(getattr(value, key))
        groups[group].append(value)
    return {name: _summarize(values) for name, values in sorted(groups.items())}


def analyze_tape_rows(
    tapes: Mapping[str, Sequence[TapeRow]], *, post_quote_horizon_ms: float = 1000.0
) -> dict[str, Any]:
    """Analyze validated tape rows and return a JSON-serializable DAT-15 artifact."""

    if post_quote_horizon_ms <= 0:
        raise ValueError("post_quote_horizon_ms must be positive")
    observations: list[AlignmentObservation] = []
    coverage: list[TapeCoverage] = []
    for tape_name, raw_rows in sorted(tapes.items()):
        rows = tuple(raw_rows)
        classifier = CaptureTradeDirectionClassifier()
        enriched = tuple(classifier.process(row) for row in rows)
        depth_quotes = _complete_depth_quotes(rows)
        prices: dict[str, _PriceState] = defaultdict(_PriceState)
        print_rows = [row for row in enriched if (row.cumulative_volume_increment or 0) > 0]
        duration_minutes = (
            max((rows[-1].receive_ts - rows[0].receive_ts).total_seconds() / 60, 1 / 60)
            if rows
            else 0
        )
        activity_rate = len(print_rows) / duration_minutes if duration_minutes else 0.0
        band = _activity_band(activity_rate)
        enriched_by_sequence = {row.receive_sequence: row for row in enriched}
        for raw in rows:
            if raw.event_type not in {"quote", "full"} or raw.last_price is None:
                continue
            state = prices[raw.instrument_id]
            prior_differing = state.before(raw.last_price)
            state.observe(raw.last_price)
            row = enriched_by_sequence[raw.receive_sequence]
            if (row.cumulative_volume_increment or 0) <= 0 or row.trade_side is None:
                continue
            tier = row.trade_quote_channel or "none"
            post = (
                _first_post_quote(
                    depth_quotes.get((row.instrument_id, tier), ()),
                    row.receive_ts,
                    post_quote_horizon_ms,
                )
                if tier != "none"
                else None
            )
            post_side: TradeSide | None = None
            post_delay: float | None = None
            if post is not None:
                post_delay = (post.receive_ts - row.receive_ts).total_seconds() * 1000
                post_side = classify_trade(
                    last_price=raw.last_price,
                    best_bid=post.best_bid,
                    best_ask=post.best_ask,
                    last_differing_trade_price=prior_differing,
                    quote_age_ms=0.0,
                    quote_freshness_bound_ms=post_quote_horizon_ms,
                    cumulative_volume_increment=row.cumulative_volume_increment or 0,
                    last_quantity=row.last_quantity or 0,
                ).side
            observations.append(
                AlignmentObservation(
                    tape_name,
                    row.instrument_id,
                    row.receive_ts,
                    activity_rate,
                    band,
                    tier,
                    row.trade_quote_age_ms,
                    row.trade_side,
                    row.trade_classification_reason or "missing",
                    bool(row.trade_classification_degraded),
                    row.cumulative_volume_increment or 0,
                    row.last_quantity or 0,
                    bool(row.trade_coalesced),
                    post_delay,
                    post_side,
                )
            )
        coverage.append(
            TapeCoverage(
                tape_name,
                len(rows),
                len(print_rows),
                activity_rate,
                band,
                tuple(sorted({row.instrument_id for row in rows})),
                tuple(
                    sorted(
                        {
                            row.event_type
                            for row in rows
                            if row.event_type in {"depth20", "depth200"}
                        }
                    )
                ),
                rows[0].receive_ts.isoformat() if rows else None,
                rows[-1].receive_ts.isoformat() if rows else None,
            )
        )
    return {
        "schema_version": "1.0.0",
        "task": "DAT-15",
        "generated_at": datetime.now(IST).isoformat(),
        "object_category": "observed quote ages; post-print classification comparison is proxy",
        "flip_proxy_definition": (
            "recorded causal side versus first complete same-tier depth BBO received after the "
            f"print within {post_quote_horizon_ms:g} ms"
        ),
        "identification_limit": (
            "Dhan deep packets lack exchange timestamps/source sequence; the post-print BBO is "
            "not identified as the true exchange-time prevailing quote and may reflect the trade"
        ),
        "post_quote_horizon_ms": post_quote_horizon_ms,
        "tape_coverage": [asdict(value) for value in coverage],
        "overall": _summarize(observations),
        "by_tape": _grouped(observations, "tape"),
        "by_instrument": _grouped(observations, "instrument_id"),
        "by_depth_tier": _grouped(observations, "depth_tier"),
        "by_time_of_day": _grouped(observations, "time_bucket"),
        "by_activity_band": _grouped(observations, "activity_band"),
        "by_quote_age_band": _grouped(observations, "quote_age_band"),
    }


def analyze_alignment_tapes(
    paths: Sequence[Path], *, post_quote_horizon_ms: float = 1000.0
) -> dict[str, Any]:
    if not paths:
        raise ValueError("at least one tape path is required")
    tapes = {str(path): tuple(JsonlTapeReader(path).rows()) for path in paths}
    return analyze_tape_rows(tapes, post_quote_horizon_ms=post_quote_horizon_ms)
