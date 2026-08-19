"""CON-07: IST timestamps and the module-wide past-only causality invariant."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Self
from zoneinfo import ZoneInfo

from pydantic import field_validator, model_validator

from .base import ContractModel

IST = ZoneInfo("Asia/Kolkata")
IST_OFFSET = timedelta(hours=5, minutes=30)

# NSE extended the equity-derivatives regular session close by ten minutes from
# 2026-08-03.  Keep the rule date-versioned: historical expiry and replay clocks must retain
# the close that was in force on their trading date.
NSE_EQUITY_DERIVATIVES_OPEN = time(hour=9, minute=15)
NSE_EQUITY_DERIVATIVES_LEGACY_CLOSE = time(hour=15, minute=30)
NSE_EQUITY_DERIVATIVES_CURRENT_CLOSE = time(hour=15, minute=40)
NSE_EQUITY_DERIVATIVES_CLOSE_CHANGE_DATE = date(2026, 8, 3)


def nse_equity_derivatives_close(trading_date: date) -> time:
    """Return the regular-session close that was in force on ``trading_date``."""

    if trading_date < NSE_EQUITY_DERIVATIVES_CLOSE_CHANGE_DATE:
        return NSE_EQUITY_DERIVATIVES_LEGACY_CLOSE
    return NSE_EQUITY_DERIVATIVES_CURRENT_CLOSE


def nse_equity_derivatives_session_bounds(trading_date: date) -> tuple[datetime, datetime]:
    """Return the date-versioned regular equity-derivatives session in IST."""

    return (
        datetime.combine(trading_date, NSE_EQUITY_DERIVATIVES_OPEN, tzinfo=IST),
        datetime.combine(trading_date, nse_equity_derivatives_close(trading_date), tzinfo=IST),
    )


def nse_equity_derivatives_session_seconds(trading_date: date) -> int:
    """Return the regular-session length for the dated NSE F&O clock."""

    opened, closed = nse_equity_derivatives_session_bounds(trading_date)
    return int((closed - opened).total_seconds())


NSE_EQUITY_DERIVATIVES_CURRENT_SESSION_SECONDS = nse_equity_derivatives_session_seconds(
    NSE_EQUITY_DERIVATIVES_CLOSE_CHANGE_DATE
)


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
