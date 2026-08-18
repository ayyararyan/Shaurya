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

    SCHEMA_VERSION: ClassVar[str] = "1.0.0"

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
    open_interest: int | None = None
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
            "open_interest": self.open_interest,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "bids": [level.to_dict() for level in self.bids],
            "asks": [level.to_dict() for level in self.asks],
            "quality_flags": [str(flag) for flag in self.quality_flags],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TapeRow:
        version = value.get("schema_version")
        if version != cls.SCHEMA_VERSION:
            raise ValueError(f"unsupported tape schema version: {version!r}")
        exchange_raw = value.get("exchange_ts")
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
            open_interest=(
                int(value["open_interest"]) if value.get("open_interest") is not None else None
            ),
            bids=tuple(DepthLevel.from_dict(item) for item in value.get("bids", [])),
            asks=tuple(DepthLevel.from_dict(item) for item in value.get("asks", [])),
            quality_flags=tuple(QualityFlag(item) for item in value.get("quality_flags", [])),
        )
