"""CON-02: versioned broker-neutral execution-ledger row contract."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import field_validator, model_validator

from .base import ContractModel
from .categories import ObjectLabel
from .timing import CausalTimestamps, require_ist


class LedgerEventType(StrEnum):
    ORDER_PLACED = "order_placed"
    ORDER_EXECUTED = "order_executed"
    CANCEL_REQUESTED = "cancel_requested"
    REJECTED = "rejected"
    CYCLE_COMPLETE = "cycle_complete"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class BookState(ContractModel):
    """Book state visible to the order decision."""

    best_bid: Decimal
    best_ask: Decimal
    mid: Decimal | None
    microprice: Decimal | None

    @model_validator(mode="after")
    def _valid_book(self) -> Self:
        if self.best_bid <= 0 or self.best_ask <= 0:
            raise ValueError("book prices must be positive")
        if self.best_bid > self.best_ask:
            raise ValueError("book state cannot be crossed")
        if self.mid is not None and self.mid <= 0:
            raise ValueError("book mid must be positive when present")
        if self.microprice is not None and self.microprice <= 0:
            raise ValueError("book microprice must be positive when present")
        return self


class LedgerRow(ContractModel):
    """One append-only lifecycle or cycle-P&L event.

    The fields reconcile Market Making's Python ``LEDGER_COLUMNS`` and native
    ``kLedgerColumns`` while replacing strategy- and broker-specific identity names with
    broker-neutral ones. Event-specific validation prevents an empty row from masquerading
    as a placement, execution, cancel/reject, or completed P&L cycle.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: str
    run_mode: str
    execution_stream: str
    event_type: LedgerEventType
    timing: CausalTimestamps
    cycle_id: str | None = None
    order_role: str | None = None
    order_id: str | None = None
    client_order_id: str | None = None
    execution_id: str | None = None
    instrument_id: str
    broker_instrument_token: str | None = None
    broker_trading_symbol: str | None = None
    side: OrderSide | None = None
    order_type: str | None = None
    time_in_force: str | None = None
    order_quantity: int | None = None
    fill_quantity: int | None = None
    remaining_quantity: int | None = None
    order_price: Decimal | None = None
    fill_price: Decimal | None = None
    quote_price: Decimal | None = None
    book_state: BookState | None = None
    width_multiplier_k: Decimal | None = None
    benchmark_reference_price: Decimal | None = None
    break_even_spread: Decimal | None = None
    benchmark_spread_ticks: int | None = None
    benchmark_spread_price: Decimal | None = None
    order_posted_at: datetime | None = None
    order_age_seconds: Decimal | None = None
    status: str
    reason: str | None = None
    cycle_pnl_rupees: Decimal | None = None
    session_pnl_rupees: Decimal | None = None
    consecutive_losses: int | None = None
    stop_reason: str | None = None
    object_labels: tuple[ObjectLabel, ...]

    @field_validator("run_id", "run_mode", "execution_stream", "instrument_id", "status")
    @classmethod
    def _required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("required ledger text fields must be non-empty")
        return value.strip()

    @field_validator("order_posted_at", mode="after")
    @classmethod
    def _posted_at_ist(cls, value: datetime | None) -> datetime | None:
        return require_ist(value, "order_posted_at") if value is not None else None

    @model_validator(mode="after")
    def _event_requirements(self) -> Self:
        if not self.object_labels:
            raise ValueError("ledger artifacts require at least one object-category label")
        label_names = [label.object_name for label in self.object_labels]
        if len(set(label_names)) != len(label_names):
            raise ValueError("ledger object-category labels must have unique object_name values")
        if (
            self.order_posted_at is not None
            and self.order_posted_at > self.timing.decision_timestamp
        ):
            raise ValueError("order_posted_at cannot be later than decision_timestamp")
        if self.order_posted_at is not None and self.order_age_seconds is not None:
            elapsed = self.timing.decision_timestamp - self.order_posted_at
            expected_age = Decimal(str(elapsed.total_seconds()))
            if self.order_age_seconds != expected_age:
                raise ValueError(
                    "order_age_seconds must equal decision_timestamp - order_posted_at"
                )
        for name in ("order_quantity", "fill_quantity"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive when present")
        if self.remaining_quantity is not None and self.remaining_quantity < 0:
            raise ValueError("remaining_quantity must be non-negative")
        if self.order_age_seconds is not None and self.order_age_seconds < 0:
            raise ValueError("order_age_seconds must be non-negative")
        for name in ("order_price", "fill_price", "quote_price"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive when present")

        required: dict[LedgerEventType, tuple[str, ...]] = {
            LedgerEventType.ORDER_PLACED: (
                "cycle_id",
                "order_role",
                "order_id",
                "side",
                "order_type",
                "time_in_force",
                "order_quantity",
                "order_price",
                "quote_price",
                "book_state",
                "width_multiplier_k",
                "break_even_spread",
                "order_posted_at",
            ),
            LedgerEventType.ORDER_EXECUTED: (
                "order_id",
                "execution_id",
                "fill_quantity",
                "remaining_quantity",
                "fill_price",
                "order_posted_at",
                "order_age_seconds",
            ),
            LedgerEventType.CANCEL_REQUESTED: ("order_id", "reason"),
            LedgerEventType.REJECTED: ("order_id", "reason"),
            LedgerEventType.CYCLE_COMPLETE: ("cycle_id", "cycle_pnl_rupees"),
        }
        missing = [name for name in required[self.event_type] if getattr(self, name) is None]
        if missing:
            raise ValueError(f"{self.event_type.value} row is missing required fields: {missing}")
        return self
