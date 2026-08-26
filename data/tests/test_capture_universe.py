from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from shaurya.contracts.instruments import (
    DhanInstrumentMapping,
    ExchangeSegment,
    InstrumentId,
    InstrumentKind,
)
from shaurya.data.capture import (
    CaptureUnderlying,
    CaptureUniversePlan,
    DhanDepth20CapturePool,
    partition_depth20_instruments,
)
from shaurya.data.dhan_client import DhanCredentials


def _mapping(security_id: int) -> DhanInstrumentMapping:
    return DhanInstrumentMapping(
        instrument=InstrumentId(
            exchange="NSE",
            segment=ExchangeSegment.NSE_FNO,
            underlying="NIFTY",
            kind=InstrumentKind.FUTURE,
            expiry=date(2026, 8, 25),
        ),
        security_id=str(security_id),
        exchange_segment=ExchangeSegment.NSE_FNO,
        trading_symbol=f"NIFTY-{security_id}-FUT",
        lot_size=65,
        tick_size_paise=Decimal("10"),
        as_of_date=date(2026, 8, 19),
        source="fixture",
    )


def test_capture_plan_keeps_unresolved_values_explicit_and_retention_permanent() -> None:
    plan = CaptureUniversePlan(
        plan_id="nse-index-fno-20260819",
        trading_date=date(2026, 8, 19),
        instrument_master_date=date(2026, 8, 19),
        underlyings=(
            CaptureUnderlying.NIFTY,
            CaptureUnderlying.BANKNIFTY,
            CaptureUnderlying.FINNIFTY,
            CaptureUnderlying.MIDCPNIFTY,
        ),
        depth20_security_ids=tuple(str(value) for value in range(1, 121)),
    )
    assert plan.retention == "permanent"
    assert plan.exact_depth20_ceiling is None
    assert plan.strike_band_rule is None
    assert plan.depth20_socket_count() == 3


def test_depth20_pool_partitions_safely_and_uses_global_sequences() -> None:
    instruments = [_mapping(value) for value in range(1, 121)]
    batches = partition_depth20_instruments(instruments)
    assert [len(batch) for batch in batches] == [50, 50, 20]
    pool = DhanDepth20CapturePool(
        DhanCredentials("client", "token"),
        instruments,
        lambda row: None,
        run_id="sha-20260818T053000.000000Z-1234abcd",
    )
    streams = pool.streams()
    assert [stream.connection_id for stream in streams] == [
        "depth20-0001",
        "depth20-0002",
        "depth20-0003",
    ]
    assert [streams[0]._next_sequence(), streams[1]._next_sequence()] == [1, 2]


@pytest.mark.asyncio
async def test_single_stream_rejects_more_than_configured_depth20_limit() -> None:
    from shaurya.data.dhan_stream import DhanLiveStream, DhanStreamConfig

    stream = DhanLiveStream(
        DhanCredentials("client", "token"),
        [_mapping(value) for value in range(1, 52)],
        lambda row: None,
        run_id="sha-20260818T053000.000000Z-1234abcd",
        config=DhanStreamConfig(enable_standard_feed=False),
    )
    with pytest.raises(ValueError, match="one subscription message"):
        await stream.run()
