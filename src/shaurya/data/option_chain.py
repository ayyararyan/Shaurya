"""DAT-04: Dhan option-chain normalization against canonical instrument identity."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import field_validator, model_validator

from shaurya.contracts.base import ContractModel
from shaurya.contracts.categories import ObjectCategory
from shaurya.contracts.instruments import (
    DhanInstrumentMapping,
    InstrumentKind,
    OptionType,
)
from shaurya.contracts.timing import require_ist
from shaurya.data.dhan_client import DhanClient


class OptionQuote(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    instrument_id: str
    broker_security_id: str
    strike: Decimal
    option_type: OptionType
    last_price: Decimal | None = None
    bid_price: Decimal | None = None
    ask_price: Decimal | None = None
    implied_volatility: Decimal | None = None
    open_interest: int | None = None
    volume: int | None = None
    category: Literal[ObjectCategory.OBSERVED] = ObjectCategory.OBSERVED

    @model_validator(mode="after")
    def _valid_quote(self) -> Self:
        if not self.instrument_id or not self.broker_security_id:
            raise ValueError("option quote identities are required")
        if self.strike <= 0:
            raise ValueError("option strike must be positive")
        prices = (self.last_price, self.bid_price, self.ask_price)
        if any(value is not None and value < 0 for value in prices):
            raise ValueError("option prices must be non-negative")
        if (
            self.bid_price is not None
            and self.ask_price is not None
            and self.bid_price > self.ask_price
        ):
            raise ValueError("option quote cannot be crossed")
        if self.open_interest is not None and self.open_interest < 0:
            raise ValueError("option open interest must be non-negative")
        if self.volume is not None and self.volume < 0:
            raise ValueError("option volume must be non-negative")
        return self


class ValidatedOptionChain(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    underlying: str
    underlying_security_id: str
    expiry: date
    captured_at: datetime
    underlying_last_price: Decimal
    master_as_of_date: date
    quotes: tuple[OptionQuote, ...]
    source: Literal["dhan"] = "dhan"
    category: Literal[ObjectCategory.OBSERVED] = ObjectCategory.OBSERVED

    @field_validator("captured_at")
    @classmethod
    def _ist_timestamp(cls, value: datetime) -> datetime:
        return require_ist(value, "captured_at")

    @model_validator(mode="after")
    def _valid_chain(self) -> Self:
        if not self.underlying or not self.underlying_security_id:
            raise ValueError("option-chain underlying identity is required")
        if self.underlying_last_price <= 0:
            raise ValueError("underlying last price must be positive")
        if not self.quotes:
            raise ValueError("validated option chain cannot be empty")
        ids = [quote.instrument_id for quote in self.quotes]
        if len(ids) != len(set(ids)):
            raise ValueError("validated option chain has duplicate contracts")
        return self


def _optional_decimal(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def validate_option_chain(
    payload: dict[str, Any],
    mappings: Iterable[DhanInstrumentMapping],
    *,
    underlying: str,
    underlying_security_id: str,
    expiry: date,
    captured_at: datetime,
) -> ValidatedOptionChain:
    """Fail closed unless each broker contract maps to the requested canonical chain."""

    mapping_by_security_id = {mapping.security_id: mapping for mapping in mappings}
    chain_rows = payload.get("oc")
    if not isinstance(chain_rows, dict) or not chain_rows:
        raise ValueError("Dhan option chain contained no contracts")
    quotes: list[OptionQuote] = []
    for strike_raw, pair in chain_rows.items():
        if not isinstance(pair, dict):
            raise ValueError(f"Dhan option-chain strike {strike_raw!r} is not an object")
        strike = Decimal(str(strike_raw))
        for side_key, option_type in (("ce", OptionType.CALL), ("pe", OptionType.PUT)):
            contract = pair.get(side_key)
            if contract is None:
                continue
            if not isinstance(contract, dict):
                raise ValueError(f"Dhan option-chain {strike} {side_key} is not an object")
            security_id = str(contract.get("security_id", ""))
            mapping = mapping_by_security_id.get(security_id)
            if mapping is None:
                raise ValueError(
                    f"Dhan option-chain security_id {security_id!r} is absent from the master"
                )
            identity = mapping.instrument
            expected = (
                identity.kind is InstrumentKind.OPTION
                and identity.underlying.upper() == underlying.upper()
                and identity.expiry == expiry
                and identity.strike == strike
                and identity.option_type is option_type
            )
            if not expected:
                raise ValueError(
                    f"Dhan option-chain identity mismatch for security_id {security_id}"
                )
            quotes.append(
                OptionQuote(
                    instrument_id=identity.canonical,
                    broker_security_id=security_id,
                    strike=strike,
                    option_type=option_type,
                    last_price=_optional_decimal(contract.get("last_price")),
                    bid_price=_optional_decimal(contract.get("top_bid_price")),
                    ask_price=_optional_decimal(contract.get("top_ask_price")),
                    implied_volatility=_optional_decimal(contract.get("implied_volatility")),
                    open_interest=_optional_int(contract.get("oi")),
                    volume=_optional_int(contract.get("volume")),
                )
            )
    master_dates = {mapping.as_of_date for mapping in mapping_by_security_id.values()}
    if len(master_dates) != 1:
        raise ValueError("option-chain validation requires one master as_of_date")
    return ValidatedOptionChain(
        underlying=underlying,
        underlying_security_id=underlying_security_id,
        expiry=expiry,
        captured_at=captured_at,
        underlying_last_price=Decimal(str(payload.get("last_price", "0"))),
        master_as_of_date=next(iter(master_dates)),
        quotes=tuple(sorted(quotes, key=lambda item: (item.strike, item.option_type.value))),
    )


def fetch_and_validate_option_chain(
    client: DhanClient,
    mappings: Iterable[DhanInstrumentMapping],
    *,
    underlying: str,
    underlying_security_id: int,
    expiry: date,
    captured_at: datetime,
    exchange_segment: str = "IDX_I",
) -> ValidatedOptionChain:
    payload = client.option_chain(
        expiry=expiry.isoformat(),
        underlying_security_id=underlying_security_id,
        exchange_segment=exchange_segment,
    )
    return validate_option_chain(
        payload,
        mappings,
        underlying=underlying,
        underlying_security_id=str(underlying_security_id),
        expiry=expiry,
        captured_at=captured_at,
    )
