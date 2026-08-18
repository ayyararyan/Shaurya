"""CON-07: IST timestamps and the module-wide past-only causality invariant."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Self
from zoneinfo import ZoneInfo

from pydantic import field_validator, model_validator

from .base import ContractModel

IST = ZoneInfo("Asia/Kolkata")
IST_OFFSET = timedelta(hours=5, minutes=30)


def require_ist(value: datetime, field_name: str = "timestamp") -> datetime:
    """Reject naive/non-IST values and normalize fixed-offset IST to Asia/Kolkata."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware IST")
    if value.utcoffset() != IST_OFFSET:
        raise ValueError(f"{field_name} must use IST (UTC+05:30)")
    return value.astimezone(IST)


class CausalTimestamps(ContractModel):
    """Exchange/receive/decision time with explicit future-information rejection.

    ``exchange_timestamp`` may be absent when the source protocol does not carry it.
    ``source_timestamps`` carries any additional upstream artifact times consulted by the
    decision. Every available source and receive time must be at or before the decision.
    """

    exchange_timestamp: datetime | None
    receive_timestamp: datetime
    decision_timestamp: datetime
    source_timestamps: tuple[datetime, ...] = ()

    @field_validator(
        "exchange_timestamp",
        "receive_timestamp",
        "decision_timestamp",
        "source_timestamps",
        mode="after",
    )
    @classmethod
    def _ist_only(cls, value: datetime | tuple[datetime, ...] | None) -> object:
        if value is None:
            return None
        if isinstance(value, tuple):
            return tuple(require_ist(item, "source_timestamp") for item in value)
        return require_ist(value)

    @model_validator(mode="after")
    def _past_only(self) -> Self:
        candidates = [self.receive_timestamp, *self.source_timestamps]
        if self.exchange_timestamp is not None:
            candidates.append(self.exchange_timestamp)
        if any(value > self.decision_timestamp for value in candidates):
            raise ValueError(
                "causality violation: no consumed timestamp may be later than decision_timestamp"
            )
        return self
