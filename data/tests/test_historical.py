from __future__ import annotations

import stat
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from shaurya.contracts.categories import ObjectCategory
from shaurya.contracts.instruments import (
    DhanInstrumentMapping,
    ExchangeSegment,
    InstrumentId,
    InstrumentKind,
)
from shaurya.data.historical import (
    BarInterval,
    HistoricalBar,
    HistoricalBarStore,
    fetch_historical_bars,
)

IST = ZoneInfo("Asia/Kolkata")


def _mapping() -> DhanInstrumentMapping:
    return DhanInstrumentMapping(
        instrument=InstrumentId(
            exchange="NSE",
            segment=ExchangeSegment.NSE_FNO,
            underlying="NIFTY",
            kind=InstrumentKind.FUTURE,
            expiry=date(2026, 8, 25),
        ),
        security_id="58072",
        exchange_segment=ExchangeSegment.NSE_FNO,
        trading_symbol="NIFTY-Aug2026-FUT",
        lot_size=65,
        tick_size_paise=Decimal("10"),
        as_of_date=date(2026, 8, 18),
        source="fixture",
    )


def _bar(at: datetime) -> HistoricalBar:
    return HistoricalBar(
        instrument_id=_mapping().instrument.canonical,
        broker_security_id="58072",
        interval=BarInterval.MINUTE_5,
        bar_start=at,
        bar_end=at + BarInterval.MINUTE_5.duration,
        open=Decimal("25000"),
        high=Decimal("25020"),
        low=Decimal("24990"),
        close=Decimal("25010"),
        volume=100,
    )


def test_fetch_intraday_bars_normalizes_schema_without_claiming_ticks() -> None:
    class FakeClient:
        def intraday_minute_data(self, **kwargs: object) -> pd.DataFrame:
            assert kwargs["interval"] == 5
            return pd.DataFrame(
                {
                    "timestamp": [pd.Timestamp("2026-08-18 09:15", tz=IST)],
                    "open": [25000.0],
                    "high": [25020.0],
                    "low": [24990.0],
                    "close": [25010.0],
                    "volume": [100],
                }
            )

    bars = fetch_historical_bars(  # type: ignore[arg-type]
        FakeClient(),
        _mapping(),
        interval=BarInterval.MINUTE_5,
        from_date=date(2026, 8, 18),
        to_date=date(2026, 8, 18),
        instrument_type="FUTIDX",
    )
    assert len(bars) == 1
    assert bars[0].interval is BarInterval.MINUTE_5
    assert bars[0].category is ObjectCategory.OBSERVED
    assert bars[0].bar_start.tzinfo == IST


def test_historical_store_round_trip_permissions_and_gap_surface(tmp_path: Path) -> None:
    start = datetime(2026, 8, 18, 9, 15, tzinfo=IST)
    bars = (_bar(start), _bar(start + BarInterval.MINUTE_5.duration * 2))
    store = HistoricalBarStore(tmp_path / "bars.parquet")
    assert store.write(bars) == 2
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert tuple(store.rows()) == bars
    assert store.gaps() == ((bars[0].bar_end, bars[1].bar_start),)
    with pytest.raises(FileExistsError):
        store.write(bars)


def test_bar_schema_rejects_naive_time_bad_ohlc_and_wrong_window() -> None:
    start = datetime(2026, 8, 18, 9, 15, tzinfo=IST)
    payload = _bar(start).model_dump()
    with pytest.raises(ValueError):
        HistoricalBar(**dict(payload, bar_start=start.replace(tzinfo=None)))
    with pytest.raises(ValueError, match="bar high"):
        HistoricalBar(**dict(payload, high=Decimal("24900")))
    with pytest.raises(ValueError, match="bar window"):
        HistoricalBar(**dict(payload, bar_end=start + BarInterval.MINUTE_15.duration))
