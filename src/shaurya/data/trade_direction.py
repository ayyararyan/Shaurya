"""DAT-14: bounded, causal trade-direction classification at capture time.

The pure :func:`classify_trade` function contains the economic rule.  The
``CaptureTradeDirectionClassifier`` adapter only maintains the bounded per-instrument quote,
volume, and tick-rule state needed to apply that rule to canonical tape rows.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from shaurya.contracts.tape import QualityFlag, TapeRow, TradeSide

TRADE_CLASSIFIER_VERSION = "quote-mid-tick-v1"
TRADE_ALIGNMENT_VERSION = "latest-complete-depth-before-print-v1"
DEPTH_CHANNELS = frozenset({"depth20", "depth200"})
PRINT_EVENT_TYPES = frozenset({"quote", "full"})


class ClassificationReason(StrEnum):
    QUOTE_RULE = "quote_rule"
    TICK_RULE = "tick_rule"
    NO_PRIOR_DIFFERING_TRADE = "no_prior_differing_trade"
    NO_PREVAILING_QUOTE = "no_prevailing_quote"
    STALE_QUOTE = "stale_quote"
    INVALID_QUOTE = "invalid_quote"


@dataclass(frozen=True, slots=True)
class TradeClassification:
    """Result of the pure classification rule, independent of stream plumbing."""

    side: TradeSide
    reason: ClassificationReason
    degraded: bool
    coalesced: bool


def classify_trade(
    *,
    last_price: float,
    best_bid: float | None,
    best_ask: float | None,
    last_differing_trade_price: float | None,
    quote_age_ms: float | None,
    quote_freshness_bound_ms: float,
    cumulative_volume_increment: int,
    last_quantity: int,
) -> TradeClassification:
    """Classify one observed print using a quote rule then a tick-rule fallback.

    A missing, crossed, or stale quote is not silently forward-filled: it produces an explicit
    degraded ``UNCLASSIFIED`` result.  Midpoint comparisons use decimal representations of the
    observed floats so a decimal tick exactly at the midpoint remains an exact comparison.
    """

    if last_price <= 0:
        raise ValueError("last_price must be positive")
    if quote_freshness_bound_ms <= 0:
        raise ValueError("quote_freshness_bound_ms must be positive")
    if cumulative_volume_increment <= 0:
        raise ValueError("cumulative_volume_increment must be positive")
    if last_quantity < 0:
        raise ValueError("last_quantity must be non-negative")
    if quote_age_ms is not None and quote_age_ms < 0:
        raise ValueError("quote_age_ms must be non-negative")

    coalesced = cumulative_volume_increment > last_quantity
    if best_bid is None or best_ask is None or quote_age_ms is None:
        return TradeClassification(
            TradeSide.UNCLASSIFIED,
            ClassificationReason.NO_PREVAILING_QUOTE,
            True,
            coalesced,
        )
    if best_bid <= 0 or best_ask <= 0 or best_bid >= best_ask:
        return TradeClassification(
            TradeSide.UNCLASSIFIED,
            ClassificationReason.INVALID_QUOTE,
            True,
            coalesced,
        )
    if quote_age_ms > quote_freshness_bound_ms:
        return TradeClassification(
            TradeSide.UNCLASSIFIED,
            ClassificationReason.STALE_QUOTE,
            True,
            coalesced,
        )

    price = Decimal(str(last_price))
    midpoint = (Decimal(str(best_bid)) + Decimal(str(best_ask))) / Decimal(2)
    if price > midpoint:
        return TradeClassification(
            TradeSide.BUY, ClassificationReason.QUOTE_RULE, False, coalesced
        )
    if price < midpoint:
        return TradeClassification(
            TradeSide.SELL, ClassificationReason.QUOTE_RULE, False, coalesced
        )
    if last_differing_trade_price is None:
        return TradeClassification(
            TradeSide.UNCLASSIFIED,
            ClassificationReason.NO_PRIOR_DIFFERING_TRADE,
            False,
            coalesced,
        )
    if last_price > last_differing_trade_price:
        return TradeClassification(
            TradeSide.BUY, ClassificationReason.TICK_RULE, False, coalesced
        )
    if last_price < last_differing_trade_price:
        return TradeClassification(
            TradeSide.SELL, ClassificationReason.TICK_RULE, False, coalesced
        )
    raise ValueError("last_differing_trade_price must differ from last_price")


@dataclass(frozen=True, slots=True)
class _QuoteState:
    channel: str
    best_bid: float
    best_ask: float
    bid_receive_ts: datetime
    ask_receive_ts: datetime

    @property
    def state_receive_ts(self) -> datetime:
        return max(self.bid_receive_ts, self.ask_receive_ts)

    def age_ms_at(self, print_receive_ts: datetime) -> float:
        # Freshness is conservative: the older of the two BBO legs determines quote age.
        return max(
            (print_receive_ts - self.bid_receive_ts).total_seconds() * 1000,
            (print_receive_ts - self.ask_receive_ts).total_seconds() * 1000,
        )


@dataclass(slots=True)
class _TradeState:
    cumulative_volume: int | None = None
    last_trade_price: float | None = None
    prior_differing_trade_price: float | None = None

    def last_differing_price(self, current_price: float) -> float | None:
        if self.last_trade_price is None:
            return None
        if current_price != self.last_trade_price:
            return self.last_trade_price
        return self.prior_differing_trade_price

    def observe_price(self, current_price: float) -> None:
        if self.last_trade_price is None:
            self.last_trade_price = current_price
        elif current_price != self.last_trade_price:
            self.prior_differing_trade_price = self.last_trade_price
            self.last_trade_price = current_price


class CaptureTradeDirectionClassifier:
    """Single-pass DAT-14 tape-row adapter with bounded per-instrument state.

    Alignment rule ``latest-complete-depth-before-print-v1``:

    * each depth20/depth200 channel becomes a candidate only after both BBO sides have been
      received in the current connection epoch;
    * at a print, choose the candidate whose composite state was updated most recently before
      the print (``max(bid_ts, ask_ts)``), breaking exact timestamp ties by channel name;
    * quote age is the age of the older BBO leg, and a candidate older than the configured bound
      is retained as raw evidence but classified as degraded/unclassified;
    * no future row, standard-packet book bundled with the print, or post-reconnect stale state is
      eligible.
    """

    def __init__(self, *, quote_freshness_seconds: float = 1.0) -> None:
        if quote_freshness_seconds <= 0:
            raise ValueError("quote_freshness_seconds must be positive")
        self.quote_freshness_bound_ms = quote_freshness_seconds * 1000
        self._side_receive_times: dict[tuple[str, str], dict[str, datetime]] = {}
        self._quotes: dict[tuple[str, str], _QuoteState] = {}
        self._trades: dict[str, _TradeState] = {}

    def process(self, row: TapeRow) -> TapeRow:
        """Return the row enriched when it is an observed positive-volume print."""

        if row.event_type in DEPTH_CHANNELS:
            self._observe_depth(row)
            return row
        if row.event_type not in PRINT_EVENT_TYPES:
            return row
        return self._observe_print(row)

    def _observe_depth(self, row: TapeRow) -> None:
        key = (row.instrument_id, row.event_type)
        if any(
            flag in row.quality_flags
            for flag in (QualityFlag.CONNECTION_GAP, QualityFlag.RECONNECTED)
        ):
            self._side_receive_times.pop(key, None)
            self._quotes.pop(key, None)
        if row.update_side not in {"bid", "ask"}:
            return
        times = self._side_receive_times.setdefault(key, {})
        times[row.update_side] = row.receive_ts
        if not row.bids or not row.asks or "bid" not in times or "ask" not in times:
            return
        self._quotes[key] = _QuoteState(
            channel=row.event_type,
            best_bid=row.bids[0].price,
            best_ask=row.asks[0].price,
            bid_receive_ts=times["bid"],
            ask_receive_ts=times["ask"],
        )

    def _prevailing_quote(self, row: TapeRow) -> _QuoteState | None:
        candidates = [
            quote
            for (instrument_id, _), quote in self._quotes.items()
            if instrument_id == row.instrument_id and quote.state_receive_ts <= row.receive_ts
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda quote: (quote.state_receive_ts, quote.channel))

    def _observe_print(self, row: TapeRow) -> TapeRow:
        if row.last_price is None or row.last_quantity is None or row.cumulative_volume is None:
            return row
        state = self._trades.setdefault(row.instrument_id, _TradeState())
        prior_volume = state.cumulative_volume
        state.cumulative_volume = row.cumulative_volume
        last_differing = state.last_differing_price(row.last_price)
        state.observe_price(row.last_price)
        if prior_volume is None or row.cumulative_volume <= prior_volume:
            return row

        increment = row.cumulative_volume - prior_volume
        quote = self._prevailing_quote(row)
        quote_age_ms = quote.age_ms_at(row.receive_ts) if quote else None
        result = classify_trade(
            last_price=row.last_price,
            best_bid=quote.best_bid if quote else None,
            best_ask=quote.best_ask if quote else None,
            last_differing_trade_price=last_differing,
            quote_age_ms=quote_age_ms,
            quote_freshness_bound_ms=self.quote_freshness_bound_ms,
            cumulative_volume_increment=increment,
            last_quantity=row.last_quantity,
        )
        flags = set(row.quality_flags)
        if result.degraded:
            flags.add(QualityFlag.TRADE_CLASSIFICATION_DEGRADED)
        if result.coalesced:
            flags.add(QualityFlag.COALESCED_PRINT)
        return replace(
            row,
            cumulative_volume_increment=increment,
            trade_quote_bid=quote.best_bid if quote else None,
            trade_quote_ask=quote.best_ask if quote else None,
            trade_quote_channel=quote.channel if quote else None,
            trade_quote_bid_receive_ts=quote.bid_receive_ts if quote else None,
            trade_quote_ask_receive_ts=quote.ask_receive_ts if quote else None,
            trade_quote_receive_ts=quote.state_receive_ts if quote else None,
            trade_quote_age_ms=quote_age_ms,
            trade_quote_freshness_bound_ms=self.quote_freshness_bound_ms,
            trade_side=result.side,
            trade_classifier_version=TRADE_CLASSIFIER_VERSION,
            trade_alignment_version=TRADE_ALIGNMENT_VERSION,
            trade_classification_degraded=result.degraded,
            trade_classification_reason=result.reason.value,
            trade_coalesced=result.coalesced,
            quality_flags=tuple(flags),
        )
