"""DAT-03: typed Dhan bar retrieval and immutable versioned Parquet storage."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterable, Iterator
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import field_validator, model_validator

from shaurya.contracts.base import ContractModel
from shaurya.contracts.categories import ObjectCategory
from shaurya.contracts.instruments import DhanInstrumentMapping
from shaurya.contracts.timing import IST, require_ist
from shaurya.data.dhan_client import DhanClient


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class BarInterval(StrEnum):
    MINUTE_1 = "1m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    MINUTE_25 = "25m"
    MINUTE_60 = "60m"
    DAY_1 = "1d"

    @property
    def duration(self) -> timedelta:
        if self is BarInterval.DAY_1:
            return timedelta(days=1)
        return timedelta(minutes=int(self.value.removesuffix("m")))

    @property
    def dhan_minutes(self) -> int:
        if self is BarInterval.DAY_1:
            raise ValueError("daily bars do not have a Dhan minute interval")
        return int(self.value.removesuffix("m"))


class HistoricalBar(ContractModel):
    """One observed OHLCV bar; this is explicitly not a tick-history contract."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    instrument_id: str
    broker_security_id: str
    interval: BarInterval
    bar_start: datetime
    bar_end: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    open_interest: int | None = None
    source: Literal["dhan"] = "dhan"
    category: Literal[ObjectCategory.OBSERVED] = ObjectCategory.OBSERVED

    @field_validator("bar_start", "bar_end")
    @classmethod
    def _ist_timestamp(cls, value: datetime, info: Any) -> datetime:
        return require_ist(value, info.field_name)

    @model_validator(mode="after")
    def _valid_bar(self) -> Self:
        if not self.instrument_id or not self.broker_security_id:
            raise ValueError("historical-bar instrument identities are required")
        if self.bar_end - self.bar_start != self.interval.duration:
            raise ValueError("bar window does not equal the declared interval")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("OHLC prices must be positive")
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("bar high is below another OHLC price")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("bar low is above another OHLC price")
        if self.volume < 0 or (self.open_interest is not None and self.open_interest < 0):
            raise ValueError("bar volume and open interest must be non-negative")
        return self


class HistoricalBarStore:
    """Write once/read many storage for a single instrument and bar interval."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, bars: Iterable[HistoricalBar]) -> int:
        if self.path.exists():
            raise FileExistsError(self.path)
        collected: list[HistoricalBar] = []
        prior: HistoricalBar | None = None
        for bar in bars:
            if prior is not None:
                same_series = (
                    bar.instrument_id == prior.instrument_id and bar.interval is prior.interval
                )
                if not same_series:
                    raise ValueError("one bar artifact must contain one instrument and interval")
                if bar.bar_start <= prior.bar_start:
                    raise ValueError("historical bars must be strictly time-ordered")
            collected.append(bar)
            prior = bar
        schema = pa.schema(
            [
                pa.field("schema_version", pa.string(), nullable=False),
                pa.field("instrument_id", pa.string(), nullable=False),
                pa.field("broker_security_id", pa.string(), nullable=False),
                pa.field("interval", pa.string(), nullable=False),
                pa.field("bar_start", pa.timestamp("ns", tz="Asia/Kolkata"), nullable=False),
                pa.field("bar_end", pa.timestamp("ns", tz="Asia/Kolkata"), nullable=False),
                pa.field("open", pa.decimal128(38, 12), nullable=False),
                pa.field("high", pa.decimal128(38, 12), nullable=False),
                pa.field("low", pa.decimal128(38, 12), nullable=False),
                pa.field("close", pa.decimal128(38, 12), nullable=False),
                pa.field("volume", pa.int64(), nullable=False),
                pa.field("open_interest", pa.int64()),
                pa.field("source", pa.string(), nullable=False),
                pa.field("category", pa.string(), nullable=False),
            ],
            metadata={b"shaurya.historical_bar_schema": b"1.0.0"},
        )
        records = [bar.model_dump(mode="python") for bar in collected]
        for record in records:
            record["interval"] = str(record["interval"])
            record["category"] = str(record["category"])
        table = pa.Table.from_pylist(records, schema=schema)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        partial = self.path.parent / f"{self.path.name}.partial-{uuid.uuid4().hex}"
        pq.write_table(table, partial, compression="zstd", version="2.6")
        verified = pq.read_table(partial)
        if not verified.schema.equals(schema, check_metadata=True) or verified.num_rows != len(
            collected
        ):
            raise ValueError("historical-bar Parquet changed during round-trip")
        with partial.open("rb") as handle:
            os.fsync(handle.fileno())
        os.chmod(partial, 0o600)
        os.rename(partial, self.path)
        _fsync_directory(self.path.parent)
        return len(collected)

    def rows(self) -> Iterator[HistoricalBar]:
        prior: HistoricalBar | None = None
        table = pq.read_table(self.path)
        if table.schema.metadata != {b"shaurya.historical_bar_schema": b"1.0.0"}:
            raise ValueError("unsupported historical-bar Parquet schema")
        for row_number, record in enumerate(table.to_pylist(), start=1):
            try:
                record["interval"] = BarInterval(record["interval"])
                record["category"] = ObjectCategory(record["category"])
                bar = HistoricalBar.model_validate(record)
            except ValueError as exc:
                raise ValueError(f"invalid historical bar at row {row_number}") from exc
            if prior is not None and bar.bar_start <= prior.bar_start:
                raise ValueError(f"historical bars are not ordered at row {row_number}")
            prior = bar
            yield bar

    def gaps(self) -> tuple[tuple[datetime, datetime], ...]:
        missing: list[tuple[datetime, datetime]] = []
        prior: HistoricalBar | None = None
        for bar in self.rows():
            if prior is not None and bar.bar_start > prior.bar_end:
                missing.append((prior.bar_end, bar.bar_start))
            prior = bar
        return tuple(missing)


def fetch_historical_bars(
    client: DhanClient,
    mapping: DhanInstrumentMapping,
    *,
    interval: BarInterval,
    from_date: date,
    to_date: date,
    instrument_type: str,
) -> tuple[HistoricalBar, ...]:
    """Fetch Dhan bars and normalize them into the stable DAT-03 schema."""

    if to_date < from_date:
        raise ValueError("historical to_date cannot precede from_date")
    if interval is BarInterval.DAY_1:
        frame = client.historical_daily_data(
            security_id=mapping.security_id,
            exchange_segment=mapping.exchange_segment.value,
            instrument_type=instrument_type,
            from_date=from_date,
            to_date=to_date,
        )
    else:
        frame = client.intraday_minute_data(
            security_id=mapping.security_id,
            exchange_segment=mapping.exchange_segment.value,
            instrument_type=instrument_type,
            from_date=from_date,
            to_date=to_date,
            interval=interval.dhan_minutes,
        )
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Dhan historical response is missing columns: {sorted(missing)}")
    bars: list[HistoricalBar] = []
    for record in frame.to_dict(orient="records"):
        timestamp = record["timestamp"]
        if not isinstance(timestamp, datetime):
            timestamp = timestamp.to_pydatetime()
        if timestamp.tzinfo is None:
            raise ValueError("Dhan historical timestamp is timezone-naive")
        start = timestamp.astimezone(IST)
        oi_raw = record.get("open_interest")
        bars.append(
            HistoricalBar(
                instrument_id=mapping.instrument.canonical,
                broker_security_id=mapping.security_id,
                interval=interval,
                bar_start=start,
                bar_end=start + interval.duration,
                open=Decimal(str(record["open"])),
                high=Decimal(str(record["high"])),
                low=Decimal(str(record["low"])),
                close=Decimal(str(record["close"])),
                volume=int(record["volume"]),
                open_interest=int(oi_raw) if oi_raw is not None else None,
            )
        )
    return tuple(sorted(bars, key=lambda bar: bar.bar_start))
