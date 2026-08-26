"""CON-01: the minimal versioned market-data tape-row contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar


class QualityFlag(StrEnum):
    """Quality facts carried with a row instead of being silently discarded."""

    SOURCE_SEQUENCE_UNAVAILABLE = "source_sequence_unavailable"
    SEQUENCE_GAP = "sequence_gap"
    DUPLICATE_SEQUENCE = "duplicate_sequence"
    SEQUENCE_REGRESSION = "sequence_regression"
    CONNECTION_GAP = "connection_gap"
    RECONNECTED = "reconnected"
    HEARTBEAT_TIMEOUT = "heartbeat_timeout"
    EXCHANGE_TIMESTAMP_MISSING = "exchange_timestamp_missing"
    EXCHANGE_TIME_REGRESSION = "exchange_time_regression"
    PARTIAL_BOOK = "partial_book"
    CROSSED_BOOK = "crossed_book"
    STALE_QUOTE = "stale_quote"
    INVALID_DEPTH = "invalid_depth"
    TRADE_CLASSIFICATION_DEGRADED = "trade_classification_degraded"
    COALESCED_PRINT = "coalesced_print"


class TradeSide(StrEnum):
    BUY = "buy"
    SELL = "sell"
    UNCLASSIFIED = "unclassified"


@dataclass(frozen=True, slots=True)
class DepthLevel:
    price: float
    quantity: int
    orders: int

    def __post_init__(self) -> None:
        if self.price <= 0:
            raise ValueError("depth price must be positive")
        if self.quantity < 0 or self.orders < 0:
            raise ValueError("depth quantity and order count must be non-negative")

    def to_dict(self) -> dict[str, int | float]:
        return {"price": self.price, "quantity": self.quantity, "orders": self.orders}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> DepthLevel:
        return cls(
            price=float(value["price"]),
            quantity=int(value["quantity"]),
            orders=int(value["orders"]),
        )


def _aware(value: datetime | None, name: str) -> None:
    if value is not None and value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class TapeRow:
    """A normalized event row preserving the full available book state.

    Dhan deep-book bid and ask packets are separate events. ``update_side`` records which
    side caused this row; ``bids`` and ``asks`` carry the latest state known at receipt time.
    """

    SCHEMA_VERSION: ClassVar[str] = "1.1.0"
    LEGACY_SCHEMA_VERSIONS: ClassVar[frozenset[str]] = frozenset({"1.0.0"})

    run_id: str
    receive_sequence: int
    connection_epoch: int
    source: str
    event_type: str
    instrument_id: str
    broker_security_id: str
    exchange_segment: str
    receive_ts: datetime
    raw_message_size_bytes: int
    connection_id: str = "primary"
    exchange_ts: datetime | None = None
    source_sequence: int | None = None
    update_side: str | None = None
    last_price: float | None = None
    last_quantity: int | None = None
    cumulative_volume: int | None = None
    cumulative_volume_increment: int | None = None
    open_interest: int | None = None
    trade_quote_bid: float | None = None
    trade_quote_ask: float | None = None
    trade_quote_channel: str | None = None
    trade_quote_bid_receive_ts: datetime | None = None
    trade_quote_ask_receive_ts: datetime | None = None
    trade_quote_receive_ts: datetime | None = None
    trade_quote_age_ms: float | None = None
    trade_quote_freshness_bound_ms: float | None = None
    trade_side: TradeSide | None = None
    trade_classifier_version: str | None = None
    trade_alignment_version: str | None = None
    trade_classification_degraded: bool | None = None
    trade_classification_reason: str | None = None
    trade_coalesced: bool | None = None
    bids: tuple[DepthLevel, ...] = field(default_factory=tuple)
    asks: tuple[DepthLevel, ...] = field(default_factory=tuple)
    quality_flags: tuple[QualityFlag, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id is required")
        if self.receive_sequence < 1 or self.connection_epoch < 1:
            raise ValueError("receive_sequence and connection_epoch must be positive")
        if not self.instrument_id or not self.broker_security_id:
            raise ValueError("instrument identities are required")
        if self.raw_message_size_bytes < 0:
            raise ValueError("raw_message_size_bytes must be non-negative")
        if not self.connection_id.strip():
            raise ValueError("connection_id is required")
        if self.source_sequence is not None and self.source_sequence < 0:
            raise ValueError("source_sequence must be non-negative")
        if self.update_side not in {None, "bid", "ask", "both"}:
            raise ValueError("update_side must be bid, ask, both, or None")
        _aware(self.receive_ts, "receive_ts")
        _aware(self.exchange_ts, "exchange_ts")
        _aware(self.trade_quote_bid_receive_ts, "trade_quote_bid_receive_ts")
        _aware(self.trade_quote_ask_receive_ts, "trade_quote_ask_receive_ts")
        _aware(self.trade_quote_receive_ts, "trade_quote_receive_ts")
        if self.cumulative_volume_increment is not None and self.cumulative_volume_increment <= 0:
            raise ValueError("cumulative_volume_increment must be positive when present")
        if self.trade_quote_age_ms is not None and self.trade_quote_age_ms < 0:
            raise ValueError("trade_quote_age_ms must be non-negative")
        if (
            self.trade_quote_freshness_bound_ms is not None
            and self.trade_quote_freshness_bound_ms <= 0
        ):
            raise ValueError("trade_quote_freshness_bound_ms must be positive")
        if self.trade_quote_channel not in {None, "depth20", "depth200"}:
            raise ValueError("trade_quote_channel must be depth20, depth200, or None")
        if self.trade_side is not None:
            required = (
                self.cumulative_volume_increment,
                self.trade_quote_freshness_bound_ms,
                self.trade_classifier_version,
                self.trade_alignment_version,
                self.trade_classification_degraded,
                self.trade_classification_reason,
                self.trade_coalesced,
            )
            if any(value is None for value in required):
                raise ValueError("classified trade rows require all classification metadata")
            if self.event_type not in {"quote", "full"}:
                raise ValueError("trade classification is only valid on quote/full print rows")
        quote_values = (
            self.trade_quote_bid,
            self.trade_quote_ask,
            self.trade_quote_bid_receive_ts,
            self.trade_quote_ask_receive_ts,
            self.trade_quote_receive_ts,
            self.trade_quote_age_ms,
            self.trade_quote_channel,
        )
        if any(value is not None for value in quote_values) and not all(
            value is not None for value in quote_values
        ):
            raise ValueError("classification quote fields must be all present or all absent")
        if (
            self.trade_quote_receive_ts is not None
            and self.trade_quote_receive_ts > self.receive_ts
        ):
            raise ValueError("classification quote cannot be received after the print")
        object.__setattr__(
            self,
            "quality_flags",
            tuple(sorted(set(self.quality_flags), key=str)),
        )

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "run_id": self.run_id,
            "receive_sequence": self.receive_sequence,
            "source_sequence": self.source_sequence,
            "connection_epoch": self.connection_epoch,
            "source": self.source,
            "event_type": self.event_type,
            "instrument_id": self.instrument_id,
            "broker_security_id": self.broker_security_id,
            "exchange_segment": self.exchange_segment,
            "exchange_ts": self.exchange_ts.isoformat() if self.exchange_ts else None,
            "receive_ts": self.receive_ts.isoformat(),
            "raw_message_size_bytes": self.raw_message_size_bytes,
            "connection_id": self.connection_id,
            "update_side": self.update_side,
            "last_price": self.last_price,
            "last_quantity": self.last_quantity,
            "cumulative_volume": self.cumulative_volume,
            "cumulative_volume_increment": self.cumulative_volume_increment,
            "open_interest": self.open_interest,
            "trade_quote_bid": self.trade_quote_bid,
            "trade_quote_ask": self.trade_quote_ask,
            "trade_quote_channel": self.trade_quote_channel,
            "trade_quote_bid_receive_ts": (
                self.trade_quote_bid_receive_ts.isoformat()
                if self.trade_quote_bid_receive_ts
                else None
            ),
            "trade_quote_ask_receive_ts": (
                self.trade_quote_ask_receive_ts.isoformat()
                if self.trade_quote_ask_receive_ts
                else None
            ),
            "trade_quote_receive_ts": (
                self.trade_quote_receive_ts.isoformat() if self.trade_quote_receive_ts else None
            ),
            "trade_quote_age_ms": self.trade_quote_age_ms,
            "trade_quote_freshness_bound_ms": self.trade_quote_freshness_bound_ms,
            "trade_side": str(self.trade_side) if self.trade_side else None,
            "trade_classifier_version": self.trade_classifier_version,
            "trade_alignment_version": self.trade_alignment_version,
            "trade_classification_degraded": self.trade_classification_degraded,
            "trade_classification_reason": self.trade_classification_reason,
            "trade_coalesced": self.trade_coalesced,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "bids": [level.to_dict() for level in self.bids],
            "asks": [level.to_dict() for level in self.asks],
            "quality_flags": [str(flag) for flag in self.quality_flags],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TapeRow:
        version = value.get("schema_version")
        if version != cls.SCHEMA_VERSION and version not in cls.LEGACY_SCHEMA_VERSIONS:
            raise ValueError(f"unsupported tape schema version: {version!r}")
        exchange_raw = value.get("exchange_ts")
        quote_bid_ts = value.get("trade_quote_bid_receive_ts")
        quote_ask_ts = value.get("trade_quote_ask_receive_ts")
        quote_ts = value.get("trade_quote_receive_ts")
        return cls(
            run_id=str(value["run_id"]),
            receive_sequence=int(value["receive_sequence"]),
            source_sequence=(
                int(value["source_sequence"])
                if value.get("source_sequence") is not None
                else None
            ),
            connection_epoch=int(value["connection_epoch"]),
            source=str(value["source"]),
            event_type=str(value["event_type"]),
            instrument_id=str(value["instrument_id"]),
            broker_security_id=str(value["broker_security_id"]),
            exchange_segment=str(value["exchange_segment"]),
            exchange_ts=datetime.fromisoformat(exchange_raw) if exchange_raw else None,
            receive_ts=datetime.fromisoformat(str(value["receive_ts"])),
            raw_message_size_bytes=int(value["raw_message_size_bytes"]),
            connection_id=str(value.get("connection_id", "primary")),
            update_side=value.get("update_side"),
            last_price=(
                float(value["last_price"]) if value.get("last_price") is not None else None
            ),
            last_quantity=(
                int(value["last_quantity"]) if value.get("last_quantity") is not None else None
            ),
            cumulative_volume=(
                int(value["cumulative_volume"])
                if value.get("cumulative_volume") is not None
                else None
            ),
            cumulative_volume_increment=(
                int(value["cumulative_volume_increment"])
                if value.get("cumulative_volume_increment") is not None
                else None
            ),
            open_interest=(
                int(value["open_interest"]) if value.get("open_interest") is not None else None
            ),
            trade_quote_bid=(
                float(value["trade_quote_bid"])
                if value.get("trade_quote_bid") is not None
                else None
            ),
            trade_quote_ask=(
                float(value["trade_quote_ask"])
                if value.get("trade_quote_ask") is not None
                else None
            ),
            trade_quote_channel=value.get("trade_quote_channel"),
            trade_quote_bid_receive_ts=(
                datetime.fromisoformat(str(quote_bid_ts)) if quote_bid_ts else None
            ),
            trade_quote_ask_receive_ts=(
                datetime.fromisoformat(str(quote_ask_ts)) if quote_ask_ts else None
            ),
            trade_quote_receive_ts=datetime.fromisoformat(str(quote_ts)) if quote_ts else None,
            trade_quote_age_ms=(
                float(value["trade_quote_age_ms"])
                if value.get("trade_quote_age_ms") is not None
                else None
            ),
            trade_quote_freshness_bound_ms=(
                float(value["trade_quote_freshness_bound_ms"])
                if value.get("trade_quote_freshness_bound_ms") is not None
                else None
            ),
            trade_side=(
                TradeSide(value["trade_side"]) if value.get("trade_side") is not None else None
            ),
            trade_classifier_version=value.get("trade_classifier_version"),
            trade_alignment_version=value.get("trade_alignment_version"),
            trade_classification_degraded=value.get("trade_classification_degraded"),
            trade_classification_reason=value.get("trade_classification_reason"),
            trade_coalesced=value.get("trade_coalesced"),
            bids=tuple(DepthLevel.from_dict(item) for item in value.get("bids", [])),
            asks=tuple(DepthLevel.from_dict(item) for item in value.get("asks", [])),
            quality_flags=tuple(QualityFlag(item) for item in value.get("quality_flags", [])),
        )
