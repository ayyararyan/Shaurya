from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from shaurya.contracts.instruments import (
    DhanInstrumentMapping,
    ExchangeSegment,
    InstrumentId,
    InstrumentKind,
    OptionType,
)
from shaurya.data.option_chain import validate_option_chain

IST = ZoneInfo("Asia/Kolkata")
EXPIRY = date(2026, 8, 25)


def _mapping(security_id: str, side: OptionType) -> DhanInstrumentMapping:
    return DhanInstrumentMapping(
        instrument=InstrumentId(
            exchange="NSE",
            segment=ExchangeSegment.NSE_FNO,
            underlying="NIFTY",
            kind=InstrumentKind.OPTION,
            expiry=EXPIRY,
            strike=Decimal("25000"),
            option_type=side,
        ),
        security_id=security_id,
        exchange_segment=ExchangeSegment.NSE_FNO,
        trading_symbol=f"NIFTY-{EXPIRY}-25000-{side.value}",
        lot_size=65,
        tick_size_paise=Decimal("5"),
        as_of_date=date(2026, 8, 18),
        source="fixture",
    )


def _payload() -> dict[str, object]:
    return {
        "last_price": 25012.0,
        "oc": {
            "25000": {
                "ce": {
                    "security_id": 12345,
                    "last_price": 120.0,
                    "top_bid_price": 119.5,
                    "top_ask_price": 120.5,
                    "oi": 1000,
                },
                "pe": {
                    "security_id": 12346,
                    "last_price": 108.0,
                    "top_bid_price": 107.5,
                    "top_ask_price": 108.5,
                    "oi": 1100,
                },
            }
        },
    }


def test_option_chain_validates_every_contract_against_master() -> None:
    chain = validate_option_chain(
        _payload(),
        [_mapping("12345", OptionType.CALL), _mapping("12346", OptionType.PUT)],
        underlying="NIFTY",
        underlying_security_id="13",
        expiry=EXPIRY,
        captured_at=datetime(2026, 8, 18, 9, 15, tzinfo=IST),
    )
    assert [quote.option_type for quote in chain.quotes] == [OptionType.CALL, OptionType.PUT]
    assert chain.master_as_of_date == date(2026, 8, 18)
    restored = type(chain).model_validate_json(chain.model_dump_json())
    assert restored == chain


def test_option_chain_rejects_unknown_or_identity_mismatched_security_id() -> None:
    with pytest.raises(ValueError, match="absent from the master"):
        validate_option_chain(
            _payload(),
            [_mapping("12345", OptionType.CALL)],
            underlying="NIFTY",
            underlying_security_id="13",
            expiry=EXPIRY,
            captured_at=datetime(2026, 8, 18, 9, 15, tzinfo=IST),
        )
    wrong_put = _mapping("12346", OptionType.CALL)
    with pytest.raises(ValueError, match="identity mismatch"):
        validate_option_chain(
            _payload(),
            [_mapping("12345", OptionType.CALL), wrong_put],
            underlying="NIFTY",
            underlying_security_id="13",
            expiry=EXPIRY,
            captured_at=datetime(2026, 8, 18, 9, 15, tzinfo=IST),
        )


def test_option_chain_rejects_crossed_quote_and_naive_capture_time() -> None:
    payload = _payload()
    oc = payload["oc"]
    assert isinstance(oc, dict)
    pair = oc["25000"]
    assert isinstance(pair, dict)
    call = pair["ce"]
    assert isinstance(call, dict)
    call["top_bid_price"] = 121.0
    with pytest.raises(ValueError, match="crossed"):
        validate_option_chain(
            payload,
            [_mapping("12345", OptionType.CALL), _mapping("12346", OptionType.PUT)],
            underlying="NIFTY",
            underlying_security_id="13",
            expiry=EXPIRY,
            captured_at=datetime(2026, 8, 18, 9, 15, tzinfo=IST),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_option_chain(
            _payload(),
            [_mapping("12345", OptionType.CALL), _mapping("12346", OptionType.PUT)],
            underlying="NIFTY",
            underlying_security_id="13",
            expiry=EXPIRY,
            captured_at=datetime(2026, 8, 18, 9, 15),
        )
