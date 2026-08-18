"""DAT-01: canonical, read-only Dhan REST client."""

from __future__ import annotations

import os
import random
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from shaurya.contracts.instruments import (
    DhanInstrumentMapping,
    ExchangeSegment,
    InstrumentId,
    InstrumentKind,
    OptionType,
)

IST = ZoneInfo("Asia/Kolkata")


class DhanAPIError(RuntimeError):
    """A sanitized Dhan data-API failure; secrets and raw authenticated URLs are excluded."""


@dataclass(frozen=True, slots=True, repr=False)
class DhanCredentials:
    client_id: str = field(repr=False)
    access_token: str = field(repr=False)
    handle: str = "environment"

    def __post_init__(self) -> None:
        if not self.client_id or not self.access_token:
            raise ValueError("Dhan client ID and access token are required")

    def __repr__(self) -> str:
        return f"DhanCredentials(handle={self.handle!r}, values=[REDACTED])"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> DhanCredentials:
        source = env if env is not None else os.environ
        return cls(
            client_id=source.get("DHAN_CLIENT_ID", "").strip(),
            access_token=source.get("DHAN_ACCESS_TOKEN", "").strip(),
            handle="environment",
        )

    @classmethod
    def from_env_file(cls, path: Path) -> DhanCredentials:
        stat = path.stat()
        if stat.st_mode & 0o077:
            raise PermissionError(f"credential file must be mode 600 or stricter: {path}")
        values: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, raw = stripped.split("=", 1)
            values[key.strip()] = raw.strip().strip('"').strip("'")
        return cls(
            client_id=values.get("DHAN_CLIENT_ID", "").strip(),
            access_token=values.get("DHAN_ACCESS_TOKEN", "").strip(),
            handle=str(path),
        )


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 4
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0
    min_interval_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if min(self.base_delay_seconds, self.max_delay_seconds, self.min_interval_seconds) < 0:
            raise ValueError("retry delays must be non-negative")


def _failure_code(response: Any) -> str | None:
    if not isinstance(response, dict):
        return None
    remarks = response.get("remarks")
    if isinstance(remarks, dict):
        raw = remarks.get("error_code") or remarks.get("errorCode")
        if raw:
            return str(raw)
    status = str(response.get("status", ""))
    return "DH-429" if "429" in status else None


class DhanClient:
    """The single Dhan data adapter used by Shaurya.

    This class intentionally has no order-placement or cancellation method. D7 authorizes
    Dhan for market data and Kotak alone for execution.
    """

    def __init__(
        self,
        credentials: DhanCredentials,
        *,
        sdk: Any | None = None,
        retry: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        random_uniform: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self.credentials = credentials
        self.retry = retry or RetryPolicy()
        self._sleep = sleep
        self._monotonic = monotonic
        self._random_uniform = random_uniform
        self._rate_lock = threading.Lock()
        self._last_call_monotonic: float | None = None
        if sdk is None:
            from dhanhq import DhanContext, dhanhq

            sdk = dhanhq(DhanContext(credentials.client_id, credentials.access_token))
        self._sdk = sdk
        self._expiry_cache: dict[tuple[int, str], tuple[float, tuple[str, ...]]] = {}

    def _rate_limit(self) -> None:
        with self._rate_lock:
            now = self._monotonic()
            if self._last_call_monotonic is not None:
                wait = self.retry.min_interval_seconds - (now - self._last_call_monotonic)
                if wait > 0:
                    self._sleep(wait)
                    now = self._monotonic()
            self._last_call_monotonic = now

    def _call(self, function: Callable[[], Any], *, context: str) -> Any:
        last_error_type = "unknown"
        last_code: str | None = None
        for attempt in range(1, self.retry.max_attempts + 1):
            try:
                self._rate_limit()
                response = function()
                code = _failure_code(response)
                status = (
                    str(response.get("status", "")).lower()
                    if isinstance(response, dict)
                    else ""
                )
                if code == "DH-429":
                    last_code = code
                    raise DhanAPIError("rate_limited")
                if status == "failure":
                    raise DhanAPIError(f"Dhan rejected {context}; code={code or 'unreported'}")
                return response
            except DhanAPIError as exc:
                last_error_type = type(exc).__name__
                if "rate_limited" not in str(exc):
                    raise
            except Exception as exc:  # SDK/network exceptions are retried, but never echoed.
                last_error_type = type(exc).__name__
            if attempt < self.retry.max_attempts:
                cap = min(
                    self.retry.max_delay_seconds,
                    self.retry.base_delay_seconds * (2 ** (attempt - 1)),
                )
                self._sleep(self._random_uniform(0.0, cap) if cap else 0.0)
        raise DhanAPIError(
            f"Dhan {context} failed after {self.retry.max_attempts} attempts; "
            f"error_type={last_error_type}; code={last_code or 'unreported'}"
        )

    @staticmethod
    def unwrap_data(response: Any) -> Any:
        if not isinstance(response, dict) or "data" not in response:
            return response
        data = response.get("data")
        if isinstance(data, dict) and "data" in data:
            return data.get("data")
        return data

    def expiry_list(
        self,
        *,
        underlying_security_id: int = 13,
        exchange_segment: str = "IDX_I",
        cache_seconds: float = 3600.0,
    ) -> tuple[str, ...]:
        key = (underlying_security_id, exchange_segment)
        now = self._monotonic()
        cached = self._expiry_cache.get(key)
        if cached and now - cached[0] < cache_seconds:
            return cached[1]
        response = self._call(
            lambda: self._sdk.expiry_list(
                under_security_id=underlying_security_id,
                under_exchange_segment=exchange_segment,
            ),
            context="expiry_list",
        )
        data = self.unwrap_data(response)
        if not isinstance(data, list) or not data:
            raise DhanAPIError("Dhan expiry_list returned no expiries")
        expiries = tuple(sorted(str(value) for value in data))
        self._expiry_cache[key] = (now, expiries)
        return expiries

    def option_chain(
        self,
        *,
        expiry: str,
        underlying_security_id: int = 13,
        exchange_segment: str = "IDX_I",
    ) -> dict[str, Any]:
        response = self._call(
            lambda: self._sdk.option_chain(
                under_security_id=underlying_security_id,
                under_exchange_segment=exchange_segment,
                expiry=expiry,
            ),
            context="option_chain",
        )
        data = self.unwrap_data(response)
        if not isinstance(data, dict):
            raise DhanAPIError("Dhan option_chain returned an invalid payload")
        return data

    def resolve_atm_option(
        self,
        side: OptionType,
        *,
        underlying: str = "NIFTY",
        underlying_security_id: int = 13,
        exchange_segment: str = "IDX_I",
        spot: float | None = None,
        now: datetime | None = None,
    ) -> DhanInstrumentMapping:
        as_of = (now or datetime.now(IST)).astimezone(IST).date()
        expiry = next(
            (
                value
                for value in self.expiry_list(
                    underlying_security_id=underlying_security_id,
                    exchange_segment=exchange_segment,
                )
                if date.fromisoformat(value) >= as_of
            ),
            None,
        )
        if expiry is None:
            raise DhanAPIError("Dhan returned no unexpired option expiry")
        chain = self.option_chain(
            expiry=expiry,
            underlying_security_id=underlying_security_id,
            exchange_segment=exchange_segment,
        )
        chain_rows = chain.get("oc")
        if not isinstance(chain_rows, dict) or not chain_rows:
            raise DhanAPIError("Dhan option_chain contained no contracts")
        reference = float(spot or chain.get("last_price") or 0.0)
        if reference <= 0:
            raise DhanAPIError("Dhan option_chain contained no positive underlying price")
        side_key = "ce" if side == OptionType.CALL else "pe"
        candidates: list[tuple[float, Decimal, dict[str, Any]]] = []
        for strike_raw, pair in chain_rows.items():
            try:
                strike = Decimal(str(strike_raw))
            except Exception:
                continue
            contract = pair.get(side_key) if isinstance(pair, dict) else None
            if isinstance(contract, dict) and contract.get("security_id"):
                candidates.append((abs(float(strike) - reference), strike, contract))
        if not candidates:
            raise DhanAPIError(f"Dhan option_chain contained no {side.value} contracts")
        _, strike, contract = min(candidates, key=lambda item: item[0])
        instrument = InstrumentId(
            exchange="NSE",
            segment=ExchangeSegment.NSE_FNO,
            underlying=underlying,
            kind=InstrumentKind.OPTION,
            expiry=date.fromisoformat(expiry),
            strike=strike,
            option_type=side,
        )
        security_id = str(contract["security_id"])
        symbol = str(
            contract.get("trading_symbol")
            or f"{underlying}-{expiry}-{format(strike, 'f')}-{side.value}"
        )
        lot_raw = contract.get("lot_size")
        return DhanInstrumentMapping(
            instrument=instrument,
            security_id=security_id,
            exchange_segment=ExchangeSegment.NSE_FNO,
            trading_symbol=symbol,
            lot_size=int(lot_raw) if lot_raw else None,
            tick_size_paise=None,
            as_of_date=as_of,
            source="Dhan option_chain REST",
        )

    def expired_options_data(
        self,
        *,
        security_id: str,
        exchange_segment: str,
        instrument_type: str,
        expiry_flag: str,
        expiry_code: int,
        strike: str,
        option_type: str,
        required_data: list[str],
        from_date: date,
        to_date: date,
        interval: int = 5,
    ) -> dict[str, Any]:
        response = self._call(
            lambda: self._sdk.expired_options_data(
                security_id=security_id,
                exchange_segment=exchange_segment,
                instrument_type=instrument_type,
                expiry_flag=expiry_flag,
                expiry_code=expiry_code,
                strike=strike,
                drv_option_type=option_type,
                required_data=required_data,
                from_date=from_date.isoformat(),
                to_date=to_date.isoformat(),
                interval=interval,
            ),
            context="expired_options_data",
        )
        return self._normalize_rolling_option(response, option_type)

    @staticmethod
    def _normalize_rolling_option(response: Any, option_type: str) -> dict[str, Any]:
        if not isinstance(response, dict):
            raise DhanAPIError("Dhan rolling-option response was not an object")
        if str(response.get("status", "")).lower() != "success":
            return response
        outer = response.get("data")
        if not isinstance(outer, dict) or not isinstance(outer.get("data"), dict):
            return response
        branch = outer["data"].get("ce" if option_type.upper() in {"CALL", "CE"} else "pe")
        if not isinstance(branch, dict) or not branch.get("timestamp"):
            return {"status": "success", "remarks": "", "data": {}}
        return {"status": "success", "remarks": "", "data": branch}

    def intraday_minute_data(
        self,
        *,
        security_id: str,
        exchange_segment: str,
        instrument_type: str,
        from_date: date,
        to_date: date,
        interval: int = 5,
    ) -> Any:
        response = self._call(
            lambda: self._sdk.intraday_minute_data(
                security_id=security_id,
                exchange_segment=exchange_segment,
                instrument_type=instrument_type,
                from_date=from_date.isoformat(),
                to_date=to_date.isoformat(),
                interval=interval,
            ),
            context="intraday_minute_data",
        )
        return self._ohlcv_frame(response)

    def historical_daily_data(
        self,
        *,
        security_id: str,
        exchange_segment: str,
        instrument_type: str,
        from_date: date,
        to_date: date,
    ) -> Any:
        response = self._call(
            lambda: self._sdk.historical_daily_data(
                security_id=security_id,
                exchange_segment=exchange_segment,
                instrument_type=instrument_type,
                from_date=from_date.isoformat(),
                to_date=to_date.isoformat(),
            ),
            context="historical_daily_data",
        )
        return self._ohlcv_frame(response)

    @staticmethod
    def _ohlcv_frame(response: Any) -> Any:
        import pandas as pd

        data = DhanClient.unwrap_data(response)
        if not isinstance(data, dict) or not data:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        frame = pd.DataFrame(data)
        if "timestamp" in frame.columns:
            timestamps = pd.to_datetime(frame["timestamp"], unit="s", errors="coerce", utc=True)
            frame = frame.copy()
            frame["timestamp"] = timestamps.dt.tz_convert(IST)
        return frame
