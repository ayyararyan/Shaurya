"""Forward selection for surface fitting — a model choice, stated per expiry.

The eSSVI fitter takes ``forward_by_expiry`` as an explicit input and never invents one.
This module makes the choice visible instead of hiding it inside the fitter: for each
expiry it either uses the traded future whose expiry matches, or reconstructs the forward
from put-call parity, and returns a `CON-06`/§7.1 object label recording which was used,
under what construction, with what assumptions and limitations.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from shaurya.contracts.categories import ObjectCategory, ObjectLabel
from shaurya.contracts.tape import TapeRow


class ForwardMethod(StrEnum):
    """How one expiry's forward was obtained."""

    TRADED_FUTURE = "traded_future"
    PUT_CALL_PARITY = "put_call_parity"


@dataclass(frozen=True, slots=True)
class ForwardChoice:
    """One expiry's forward, the method that produced it, and its labelled provenance."""

    expiry: date
    forward: float
    method: ForwardMethod
    source_instrument_ids: tuple[str, ...]
    label: ObjectLabel
    parity_strike: float | None = None
    parity_candidate_strikes: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "expiry": self.expiry.isoformat(),
            "forward": self.forward,
            "method": self.method.value,
            "source_instrument_ids": list(self.source_instrument_ids),
            "parity_strike": self.parity_strike,
            "parity_candidate_strikes": self.parity_candidate_strikes,
            "label": self.label.model_dump(mode="json"),
        }


@dataclass(frozen=True, slots=True)
class ForwardSelection:
    """Forwards resolved for the requested expiries, plus explicit per-expiry failures."""

    choices: tuple[ForwardChoice, ...]
    unresolved: tuple[tuple[date, str], ...]

    @property
    def forward_by_expiry(self) -> dict[date, float]:
        return {choice.expiry: choice.forward for choice in self.choices}

    def to_dict(self) -> dict[str, object]:
        return {
            "choices": [choice.to_dict() for choice in self.choices],
            "unresolved": [
                {"expiry": expiry.isoformat(), "reason": reason}
                for expiry, reason in self.unresolved
            ],
        }


@dataclass(frozen=True, slots=True)
class _Mid:
    instrument_id: str
    mid: float


def _mid(row: TapeRow) -> float | None:
    bid = row.best_bid
    ask = row.best_ask
    if bid is None or ask is None or bid <= 0 or ask < bid:
        return None
    return 0.5 * (bid + ask)


def _future_expiry(instrument_id: str) -> date | None:
    parts = instrument_id.split(":")
    if len(parts) != 5 or parts[3].lower() != "future":
        return None
    try:
        return date.fromisoformat(parts[4])
    except ValueError:
        return None


def _option_key(instrument_id: str) -> tuple[date, float, str] | None:
    parts = instrument_id.split(":")
    if len(parts) != 7 or parts[3].lower() != "option":
        return None
    try:
        expiry = date.fromisoformat(parts[4])
        strike = float(parts[5])
    except ValueError:
        return None
    option_type = parts[6].upper()
    if strike <= 0 or option_type not in {"CE", "PE"}:
        return None
    return expiry, strike, option_type


def _latest_by_instrument(rows: Iterable[TapeRow]) -> dict[str, TapeRow]:
    latest: dict[str, TapeRow] = {}
    for row in rows:
        incumbent = latest.get(row.instrument_id)
        if incumbent is None or (row.receive_ts, row.receive_sequence) > (
            incumbent.receive_ts,
            incumbent.receive_sequence,
        ):
            latest[row.instrument_id] = row
    return latest


def _future_label(instrument_id: str) -> ObjectLabel:
    return ObjectLabel(
        object_name="forward",
        category=ObjectCategory.DERIVED,
        source=instrument_id,
        construction="mid of the observed best bid and best ask of the matching traded future",
        assumptions=(
            "the future's expiry is the option expiry, so no interpolation across expiries",
            "the mid of a two-sided book is the fair forward level",
        ),
        limitations=(
            "the mid inherits the future's quoted spread and its own quote staleness",
        ),
    )


def _parity_label(
    *,
    call_id: str,
    put_id: str,
    strike: float,
    risk_free_rate: float,
    maturity_years: float,
) -> ObjectLabel:
    return ObjectLabel(
        object_name="forward",
        category=ObjectCategory.DERIVED,
        source=f"{call_id}|{put_id}",
        construction=(
            f"put-call parity at strike {strike:g}: "
            f"F = K + exp(r*T)*(C_mid - P_mid) with r={risk_free_rate:g}, T={maturity_years:.6f}y"
        ),
        assumptions=(
            "European exercise, which NSE index options satisfy",
            f"a flat continuously-compounded rate r={risk_free_rate:g} over the option's life",
            "the strike with the smallest |C_mid - P_mid| is the least parity-noisy strike",
        ),
        limitations=(
            "no traded future exists for this expiry, so the forward is reconstructed, "
            "not read off a traded instrument",
            "parity noise from the two option spreads propagates directly into the forward",
        ),
    )


def select_forwards(
    *,
    rows: Iterable[TapeRow],
    expiries: Iterable[date],
    maturity_years_by_expiry: Mapping[date, float],
    risk_free_rate: float = 0.0,
) -> ForwardSelection:
    """Choose one forward per expiry: traded future where it exists, parity otherwise."""

    latest = _latest_by_instrument(rows)
    futures_by_expiry: dict[date, _Mid] = {}
    options: dict[tuple[date, float], dict[str, _Mid]] = {}

    for instrument_id, row in latest.items():
        mid = _mid(row)
        if mid is None:
            continue
        future_expiry = _future_expiry(instrument_id)
        if future_expiry is not None:
            futures_by_expiry[future_expiry] = _Mid(instrument_id, mid)
            continue
        option_key = _option_key(instrument_id)
        if option_key is None:
            continue
        expiry, strike, option_type = option_key
        options.setdefault((expiry, strike), {})[option_type] = _Mid(instrument_id, mid)

    choices: list[ForwardChoice] = []
    unresolved: list[tuple[date, str]] = []
    for expiry in sorted(set(expiries)):
        traded = futures_by_expiry.get(expiry)
        if traded is not None:
            choices.append(
                ForwardChoice(
                    expiry=expiry,
                    forward=traded.mid,
                    method=ForwardMethod.TRADED_FUTURE,
                    source_instrument_ids=(traded.instrument_id,),
                    label=_future_label(traded.instrument_id),
                )
            )
            continue
        maturity = maturity_years_by_expiry.get(expiry)
        if maturity is None or maturity <= 0:
            unresolved.append((expiry, "no traded future and no positive maturity for parity"))
            continue
        pairs = [
            (strike, quotes["CE"], quotes["PE"])
            for (option_expiry, strike), quotes in options.items()
            if option_expiry == expiry and "CE" in quotes and "PE" in quotes
        ]
        if not pairs:
            unresolved.append(
                (expiry, "no traded future and no strike with two-sided CE and PE quotes")
            )
            continue
        strike, call, put = min(pairs, key=lambda item: (abs(item[1].mid - item[2].mid), item[0]))
        forward = strike + math.exp(risk_free_rate * maturity) * (call.mid - put.mid)
        if forward <= 0:
            unresolved.append((expiry, "put-call parity produced a non-positive forward"))
            continue
        choices.append(
            ForwardChoice(
                expiry=expiry,
                forward=forward,
                method=ForwardMethod.PUT_CALL_PARITY,
                source_instrument_ids=(call.instrument_id, put.instrument_id),
                label=_parity_label(
                    call_id=call.instrument_id,
                    put_id=put.instrument_id,
                    strike=strike,
                    risk_free_rate=risk_free_rate,
                    maturity_years=maturity,
                ),
                parity_strike=strike,
                parity_candidate_strikes=len(pairs),
            )
        )
    return ForwardSelection(choices=tuple(choices), unresolved=tuple(unresolved))
