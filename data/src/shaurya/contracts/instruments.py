"""CON-05: canonical instrument identity and Dhan security-ID mappings."""

from __future__ import annotations

import csv
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path


class ExchangeSegment(StrEnum):
    IDX_I = "IDX_I"
    NSE_EQ = "NSE_EQ"
    NSE_FNO = "NSE_FNO"


class InstrumentKind(StrEnum):
    INDEX = "index"
    EQUITY = "equity"
    FUTURE = "future"
    OPTION = "option"


class OptionType(StrEnum):
    CALL = "CE"
    PUT = "PE"


@dataclass(frozen=True, slots=True)
class InstrumentId:
    """Broker-neutral identity for one listed instrument."""

    exchange: str
    segment: ExchangeSegment
    underlying: str
    kind: InstrumentKind
    expiry: date | None = None
    strike: Decimal | None = None
    option_type: OptionType | None = None

    def __post_init__(self) -> None:
        if not self.exchange or not self.underlying:
            raise ValueError("exchange and underlying are required")
        if self.kind in {InstrumentKind.FUTURE, InstrumentKind.OPTION} and self.expiry is None:
            raise ValueError("derivative instruments require expiry")
        if self.kind is InstrumentKind.OPTION:
            if self.strike is None or self.strike <= 0 or self.option_type is None:
                raise ValueError("options require positive strike and option_type")
        elif self.strike is not None or self.option_type is not None:
            raise ValueError("strike and option_type are valid only for options")

    @property
    def canonical(self) -> str:
        parts = [
            self.exchange.upper(),
            self.segment.value,
            self.underlying.upper(),
            self.kind.value,
        ]
        if self.expiry:
            parts.append(self.expiry.isoformat())
        if self.strike is not None:
            parts.append(format(self.strike.normalize(), "f"))
        if self.option_type:
            parts.append(self.option_type.value)
        return ":".join(parts)


@dataclass(frozen=True, slots=True)
class DhanInstrumentMapping:
    instrument: InstrumentId
    security_id: str
    exchange_segment: ExchangeSegment
    trading_symbol: str
    lot_size: int | None
    tick_size_paise: Decimal | None
    as_of_date: date
    source: str

    def __post_init__(self) -> None:
        if not self.security_id.isdigit() or int(self.security_id) <= 0:
            raise ValueError("Dhan security_id must be a positive integer string")
        if self.exchange_segment is not self.instrument.segment:
            raise ValueError("mapping segment must match internal instrument segment")
        if not self.trading_symbol:
            raise ValueError("trading_symbol is required")


@dataclass(frozen=True, slots=True)
class KotakInstrumentMapping:
    """Date-stamped Kotak routing identity for the same broker-neutral instrument."""

    instrument: InstrumentId
    instrument_token: str
    exchange_segment: str
    trading_symbol: str
    as_of_date: date
    source: str

    def __post_init__(self) -> None:
        if not self.instrument_token.strip():
            raise ValueError("Kotak instrument_token is required")
        if not self.exchange_segment.strip() or not self.trading_symbol.strip():
            raise ValueError("Kotak exchange segment and trading symbol are required")


def _date(raw: str) -> date | None:
    text = raw.strip()
    if not text:
        return None
    return datetime.fromisoformat(text).date()


def _decimal(raw: str) -> Decimal | None:
    text = raw.strip()
    if not text:
        return None
    value = Decimal(text)
    return value if value >= 0 else None


def _int_size(raw: str) -> int | None:
    value = _decimal(raw)
    if value is None:
        return None
    return int(value)


def _underlying(row: dict[str, str]) -> str:
    symbol = row.get("SM_SYMBOL_NAME", "").strip()
    trading = row.get("SEM_TRADING_SYMBOL", "").strip()
    custom = row.get("SEM_CUSTOM_SYMBOL", "").strip()
    if symbol:
        return symbol
    if "-" in trading:
        return trading.split("-", 1)[0]
    if custom:
        return custom.split()[0]
    return trading


def _identity(row: dict[str, str]) -> InstrumentId | None:
    instrument_name = row.get("SEM_INSTRUMENT_NAME", "").strip().upper()
    segment_code = row.get("SEM_SEGMENT", "").strip().upper()
    if instrument_name.startswith("OPT"):
        segment = ExchangeSegment.NSE_FNO
        kind = InstrumentKind.OPTION
    elif instrument_name.startswith("FUT"):
        segment = ExchangeSegment.NSE_FNO
        kind = InstrumentKind.FUTURE
    elif instrument_name in {"INDEX", "IDX"} or segment_code == "I":
        segment = ExchangeSegment.IDX_I
        kind = InstrumentKind.INDEX
    elif segment_code == "E" or instrument_name in {"EQUITY", "EQ"}:
        segment = ExchangeSegment.NSE_EQ
        kind = InstrumentKind.EQUITY
    else:
        return None

    expiry = _date(row.get("SEM_EXPIRY_DATE", ""))
    strike = _decimal(row.get("SEM_STRIKE_PRICE", ""))
    option_raw = row.get("SEM_OPTION_TYPE", "").strip().upper()
    option_type = OptionType(option_raw) if option_raw in {"CE", "PE"} else None
    if kind is not InstrumentKind.OPTION:
        strike = None
        option_type = None
    return InstrumentId(
        exchange="NSE",
        segment=segment,
        underlying=_underlying(row),
        kind=kind,
        expiry=expiry,
        strike=strike,
        option_type=option_type,
    )


class DhanInstrumentMaster:
    """Streaming reader for Dhan's compact security master.

    Broker mappings are explicitly date-stamped because DAT-07 will refresh them daily.
    This class defines identity/mapping semantics only; it does not choose refresh policy.
    """

    REQUIRED_COLUMNS = frozenset(
        {
            "SEM_EXM_EXCH_ID",
            "SEM_SEGMENT",
            "SEM_SMST_SECURITY_ID",
            "SEM_INSTRUMENT_NAME",
            "SEM_TRADING_SYMBOL",
            "SEM_EXPIRY_DATE",
            "SEM_STRIKE_PRICE",
            "SEM_OPTION_TYPE",
        }
    )

    def __init__(self, path: Path, *, as_of_date: date | None = None) -> None:
        self.path = path
        self.as_of_date = as_of_date or date.fromtimestamp(path.stat().st_mtime)

    def mappings(self) -> Iterator[DhanInstrumentMapping]:
        with self.path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            missing = self.REQUIRED_COLUMNS.difference(reader.fieldnames or ())
            if missing:
                raise ValueError(f"Dhan master is missing columns: {sorted(missing)}")
            for row in reader:
                if row.get("SEM_EXM_EXCH_ID", "").strip().upper() != "NSE":
                    continue
                instrument = _identity(row)
                if instrument is None:
                    continue
                security_id = row.get("SEM_SMST_SECURITY_ID", "").strip()
                if not security_id.isdigit() or int(security_id) <= 0:
                    continue
                yield DhanInstrumentMapping(
                    instrument=instrument,
                    security_id=security_id,
                    exchange_segment=instrument.segment,
                    trading_symbol=row.get("SEM_TRADING_SYMBOL", "").strip(),
                    lot_size=_int_size(row.get("SEM_LOT_UNITS", "")),
                    # Dhan's compact master expresses SEM_TICK_SIZE in paise.
                    tick_size_paise=_decimal(row.get("SEM_TICK_SIZE", "")),
                    as_of_date=self.as_of_date,
                    source=str(self.path),
                )

    def find_by_security_id(
        self,
        security_id: str,
        *,
        exchange_segment: ExchangeSegment | str | None = None,
        instrument_kind: InstrumentKind | str | None = None,
    ) -> DhanInstrumentMapping:
        wanted = str(security_id)
        segment = ExchangeSegment(exchange_segment) if exchange_segment is not None else None
        kind = InstrumentKind(instrument_kind) if instrument_kind is not None else None
        matches = [
            mapping
            for mapping in self.mappings()
            if mapping.security_id == wanted
            and (segment is None or mapping.exchange_segment is segment)
            and (kind is None or mapping.instrument.kind is kind)
        ]
        if not matches:
            filters = []
            if segment is not None:
                filters.append(f"segment={segment.value}")
            if kind is not None:
                filters.append(f"kind={kind.value}")
            suffix = f" with {', '.join(filters)}" if filters else ""
            raise KeyError(f"Dhan security_id {wanted}{suffix} was not found in {self.path}")
        if len(matches) > 1:
            identities = ", ".join(
                f"{mapping.exchange_segment.value}/{mapping.instrument.kind.value}/"
                f"{mapping.trading_symbol}"
                for mapping in matches
            )
            raise ValueError(
                f"Dhan security_id {wanted} is ambiguous in {self.path}: {identities}; "
                "pass exchange_segment or instrument_kind"
            )
        return matches[0]


def _kotak_expiry(row: dict[str, str]) -> date | None:
    raw = row.get("pExpiryDate", "").strip()
    for pattern in ("%d%b%Y", "%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, pattern).date()
        except ValueError:
            pass
    reference = row.get("pScripRefKey", "").strip().upper()
    match = re.search(r"(\d{1,2})([A-Z]{3})(\d{2})", reference)
    if match:
        day, month, year = match.groups()
        try:
            return datetime.strptime(f"{int(day):02d}{month}20{year}", "%d%b%Y").date()
        except ValueError:
            return None
    return None


def _kotak_strike(row: dict[str, str]) -> Decimal | None:
    for key in ("dStrikePrice", "dStrikePrice;"):
        raw = row.get(key, "").strip()
        if raw in {"", "-1"}:
            continue
        value = Decimal(raw)
        while value >= Decimal("100000"):
            value /= Decimal("100")
        return value if value > 0 else None
    return None


class KotakInstrumentMaster:
    """Parser for Kotak Neo's NSE F&O scrip master; identity is routing-only under D18."""

    REQUIRED_COLUMNS = frozenset(
        {"pSymbol", "pSymbolName", "pTrdSymbol", "pInstType", "pOptionType"}
    )

    def __init__(
        self,
        path: Path,
        *,
        as_of_date: date | None = None,
        exchange_segment: str = "nse_fo",
    ) -> None:
        self.path = path
        self.as_of_date = as_of_date or date.fromtimestamp(path.stat().st_mtime)
        self.exchange_segment = exchange_segment

    def mappings(self) -> Iterator[KotakInstrumentMapping]:
        with self.path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            missing = self.REQUIRED_COLUMNS.difference(reader.fieldnames or ())
            if missing:
                raise ValueError(f"Kotak master is missing columns: {sorted(missing)}")
            for row in reader:
                instrument_type = row.get("pInstType", "").strip().upper()
                if instrument_type not in {"FUTIDX", "OPTIDX"}:
                    continue
                expiry = _kotak_expiry(row)
                if expiry is None:
                    continue
                kind = (
                    InstrumentKind.OPTION
                    if instrument_type == "OPTIDX"
                    else InstrumentKind.FUTURE
                )
                option_raw = row.get("pOptionType", "").strip().upper()
                option_type = (
                    OptionType(option_raw)
                    if kind is InstrumentKind.OPTION and option_raw in {"CE", "PE"}
                    else None
                )
                strike = _kotak_strike(row) if kind is InstrumentKind.OPTION else None
                if kind is InstrumentKind.OPTION and (strike is None or option_type is None):
                    continue
                token = row.get("pSymbol", "").strip()
                trading_symbol = row.get("pTrdSymbol", "").strip()
                if not token or not trading_symbol:
                    continue
                instrument = InstrumentId(
                    exchange="NSE",
                    segment=ExchangeSegment.NSE_FNO,
                    underlying=row.get("pSymbolName", "").strip(),
                    kind=kind,
                    expiry=expiry,
                    strike=strike,
                    option_type=option_type,
                )
                yield KotakInstrumentMapping(
                    instrument=instrument,
                    instrument_token=token,
                    exchange_segment=self.exchange_segment,
                    trading_symbol=trading_symbol,
                    as_of_date=self.as_of_date,
                    source=str(self.path),
                )

    def find_by_instrument_token(self, instrument_token: str) -> KotakInstrumentMapping:
        wanted = str(instrument_token)
        for mapping in self.mappings():
            if mapping.instrument_token == wanted:
                return mapping
        raise KeyError(f"Kotak instrument_token {wanted} was not found in {self.path}")
