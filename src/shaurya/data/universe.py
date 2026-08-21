"""DAT-owned option-chain universe selection for shared capture requests."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from shaurya.contracts.instruments import (
    DhanInstrumentMapping,
    InstrumentKind,
    OptionType,
)


@dataclass(frozen=True, slots=True)
class ChainUniverse:
    """An ordered Standard/Full subscription universe plus its explicit selection."""

    underlying: str
    spot_reference: float
    expiries: tuple[date, ...]
    strike_window_fraction: float
    futures: tuple[DhanInstrumentMapping, ...]
    options: tuple[DhanInstrumentMapping, ...]

    @property
    def instruments(self) -> tuple[DhanInstrumentMapping, ...]:
        return self.futures + self.options

    def to_dict(self) -> dict[str, object]:
        return {
            "underlying": self.underlying,
            "spot_reference": self.spot_reference,
            "expiries": [expiry.isoformat() for expiry in self.expiries],
            "strike_window_fraction": self.strike_window_fraction,
            "future_count": len(self.futures),
            "option_count": len(self.options),
            "total_instruments": len(self.instruments),
            "futures": [mapping.instrument.canonical for mapping in self.futures],
            "options": [mapping.instrument.canonical for mapping in self.options],
        }


def _sort_key(mapping: DhanInstrumentMapping, spot: float) -> tuple[float, str]:
    strike = float(mapping.instrument.strike or 0)
    return abs(strike - spot), mapping.instrument.canonical


def select_chain_universe(
    mappings: Iterable[DhanInstrumentMapping],
    *,
    underlying: str,
    expiries: Sequence[date],
    spot_reference: float,
    strike_window_fraction: float = 0.06,
    max_options: int = 120,
) -> ChainUniverse:
    """Select both option wings and matching futures; acquisition remains a DAT concern."""

    if spot_reference <= 0:
        raise ValueError("spot_reference must be positive")
    if not 0 < strike_window_fraction <= 1:
        raise ValueError("strike_window_fraction must lie in (0, 1]")
    if max_options <= 0:
        raise ValueError("max_options must be positive")
    wanted_expiries = tuple(sorted(set(expiries)))
    if not wanted_expiries:
        raise ValueError("at least one expiry is required")
    target = underlying.upper()
    low = spot_reference * (1.0 - strike_window_fraction)
    high = spot_reference * (1.0 + strike_window_fraction)

    futures: list[DhanInstrumentMapping] = []
    per_expiry: dict[date, list[DhanInstrumentMapping]] = {
        expiry: [] for expiry in wanted_expiries
    }
    for mapping in mappings:
        instrument = mapping.instrument
        if instrument.underlying.upper() != target or instrument.expiry not in per_expiry:
            continue
        if instrument.kind is InstrumentKind.FUTURE:
            futures.append(mapping)
            continue
        if instrument.kind is not InstrumentKind.OPTION or instrument.strike is None:
            continue
        if instrument.option_type not in {OptionType.CALL, OptionType.PUT}:
            continue
        strike = float(instrument.strike)
        if not low <= strike <= high:
            continue
        per_expiry[instrument.expiry].append(mapping)

    for expiry in per_expiry:
        per_expiry[expiry].sort(key=lambda mapping: _sort_key(mapping, spot_reference))

    selected: list[DhanInstrumentMapping] = []
    cursors = dict.fromkeys(wanted_expiries, 0)
    while len(selected) < max_options:
        progressed = False
        for expiry in wanted_expiries:
            bucket = per_expiry[expiry]
            index = cursors[expiry]
            if index >= len(bucket):
                continue
            selected.append(bucket[index])
            cursors[expiry] = index + 1
            progressed = True
            if len(selected) >= max_options:
                break
        if not progressed:
            break

    futures.sort(key=lambda mapping: (mapping.instrument.expiry or date.max))
    return ChainUniverse(
        underlying=target,
        spot_reference=spot_reference,
        expiries=wanted_expiries,
        strike_window_fraction=strike_window_fraction,
        futures=tuple(futures),
        options=tuple(selected),
    )

