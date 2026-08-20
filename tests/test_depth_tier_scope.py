"""D33: the depth tier follows the instrument class; options never reach 200 levels."""

from __future__ import annotations

import argparse
import asyncio
from datetime import date
from decimal import Decimal

import pytest

from shaurya.cli.capture_dhan import _parser, _validate_depth_tier_scope
from shaurya.contracts.instruments import (
    DhanInstrumentMapping,
    ExchangeSegment,
    InstrumentId,
    InstrumentKind,
    OptionType,
)
from shaurya.data.dhan_client import DhanCredentials
from shaurya.data.dhan_stream import (
    DEPTH200_ELIGIBLE_KINDS,
    OPTION_MAX_DEPTH_LEVELS,
    DhanLiveStream,
    DhanStreamConfig,
)


def _future() -> DhanInstrumentMapping:
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
        as_of_date=date(2026, 8, 19),
        source="fixture",
    )


def _option() -> DhanInstrumentMapping:
    return DhanInstrumentMapping(
        instrument=InstrumentId(
            exchange="NSE",
            segment=ExchangeSegment.NSE_FNO,
            underlying="NIFTY",
            kind=InstrumentKind.OPTION,
            expiry=date(2026, 8, 25),
            strike=Decimal("24200"),
            option_type=OptionType.CALL,
        ),
        security_id="58099",
        exchange_segment=ExchangeSegment.NSE_FNO,
        trading_symbol="NIFTY-Aug2026-24200-CE",
        lot_size=65,
        tick_size_paise=Decimal("5"),
        as_of_date=date(2026, 8, 19),
        source="fixture",
    )


def _credentials() -> DhanCredentials:
    return DhanCredentials(client_id="client", access_token="token")


def _refusing_connect_factory(*args: object, **kwargs: object) -> object:
    raise OSError("no socket is opened in this test")


def _stream(mapping: DhanInstrumentMapping, config: DhanStreamConfig) -> DhanLiveStream:
    return DhanLiveStream(
        _credentials(),
        [mapping],
        lambda row: None,
        run_id="run",
        config=config,
        connect_factory=_refusing_connect_factory,
    )


def _cli_args(*extra: str) -> argparse.Namespace:
    return _parser().parse_args(
        [
            "--credentials",
            "credentials.env",
            "--security-master",
            "master.csv",
            "--security-id",
            "58099",
            "--expected-symbol",
            "NIFTY-Aug2026-24200-CE",
            *extra,
        ]
    )


def test_registered_depth200_eligibility_is_futures_and_equity_only() -> None:
    assert frozenset({InstrumentKind.EQUITY, InstrumentKind.FUTURE}) == DEPTH200_ELIGIBLE_KINDS
    assert InstrumentKind.OPTION not in DEPTH200_ELIGIBLE_KINDS
    assert OPTION_MAX_DEPTH_LEVELS == 20


def test_depth200_is_not_enabled_by_default() -> None:
    assert DhanStreamConfig().enable_200_level_depth is False


def test_stream_rejects_an_option_on_the_depth200_channel() -> None:
    config = DhanStreamConfig(
        enable_standard_feed=False,
        enable_20_level_depth=False,
        enable_200_level_depth=True,
    )

    with pytest.raises(ValueError, match="restricted to futures and equity books"):
        asyncio.run(_stream(_option(), config).run())


def test_stream_accepts_an_option_on_the_depth20_channel() -> None:
    config = DhanStreamConfig(
        enable_standard_feed=False,
        enable_20_level_depth=True,
        enable_200_level_depth=False,
    )

    async def attempt() -> None:
        # The channel list is built before any socket is opened, and this factory refuses
        # every connection, so the run can only end in a transport failure or the timeout —
        # never in the D33 eligibility error, which is the point of the test.
        await asyncio.wait_for(_stream(_option(), config).run(), timeout=0.3)

    with pytest.raises(BaseException) as excinfo:
        asyncio.run(attempt())
    assert "restricted to futures and equity books" not in str(excinfo.value)


def test_cli_rejects_depth200_for_an_option() -> None:
    with pytest.raises(ValueError, match="restricted to futures and equity books"):
        _validate_depth_tier_scope(_cli_args("--enable-depth200"), _option())


def test_cli_allows_depth200_for_a_future() -> None:
    _validate_depth_tier_scope(_cli_args("--enable-depth200"), _future())


def test_cli_allows_depth20_only_capture_for_an_option() -> None:
    _validate_depth_tier_scope(_cli_args(), _option())


def test_sig21_calibration_requires_a_future() -> None:
    # Isolated from the depth200 eligibility check, which would otherwise fire first.
    args = _cli_args("--sig21-calibration")

    with pytest.raises(ValueError, match="registered on the NIFTY front-month future"):
        _validate_depth_tier_scope(args, _option())


def test_sig21_calibration_accepts_the_front_month_future() -> None:
    _validate_depth_tier_scope(_cli_args("--enable-depth200", "--sig21-calibration"), _future())
