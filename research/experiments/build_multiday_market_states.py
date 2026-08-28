"""Stream a Shaurya NIFTY option tape into causal five-second market states."""

# ruff: noqa: UP017, UP045 - remote PyTorch environment uses Python 3.9.

from __future__ import annotations

import argparse
import json
import math
import time
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Optional

import numpy as np
import orjson

from shaurya.research.option_surface_alpha import (
    SURFACE_FACTOR_NAMES,
    SurfaceQuote,
    fit_surface_factors,
)

NS = 1_000_000_000
GRID_NS = 5 * NS
MAX_QUOTE_AGE_NS = 10 * NS
POST_RECONNECT_BUFFER_NS = 30 * NS
MONEYNESS_LIMIT = 0.015
SECONDS_PER_YEAR = 365.25 * 24.0 * 60.0 * 60.0
RISK_FREE_RATE = 0.06


FUTURE_COLUMNS = [
    "futures_log_mid",
    "futures_relative_spread",
    "futures_microprice_dislocation",
    "futures_depth_imbalance",
    "futures_log_trade_intensity_10s",
    "futures_realized_volatility_30s",
    "futures_return_5s",
]
AGGREGATE_FIELDS = [
    "option_mid_to_future",
    "option_relative_spread",
    "option_microprice_dislocation",
    "option_depth_imbalance",
    "option_return_5s",
]
ATM_FIELDS = [
    "option_mid_to_future",
    "option_relative_spread",
    "option_depth_imbalance",
]


def output_columns() -> list[str]:
    columns = list(FUTURE_COLUMNS)
    for field in AGGREGATE_FIELDS:
        for expiry in ("near", "far"):
            for kind in ("CE", "PE"):
                columns.append(f"{field}__{expiry}__{kind}")
    for field in ATM_FIELDS:
        for expiry in ("near", "far"):
            for kind in ("CE", "PE"):
                columns.append(f"atm__{field}__{expiry}__{kind}")
    columns.extend(
        [
            "atm_near_straddle_to_future",
            "atm_near_call_put_skew",
            "atm_far_straddle_to_future",
            "atm_far_call_put_skew",
        ]
    )
    for expiry in ("near", "far"):
        columns.extend(f"surface__{field}__{expiry}" for field in SURFACE_FACTOR_NAMES)
        columns.extend(
            [
                f"atm__strike__{expiry}",
                f"atm__straddle_bid_to_future__{expiry}",
                f"atm__straddle_ask_to_future__{expiry}",
            ]
        )
    return columns


@dataclass
class QuoteState:
    timestamp_ns: int
    epoch: int
    mid: float
    bid: float
    ask: float
    relative_spread: float
    microprice_dislocation: float
    depth_imbalance: float
    strike: Optional[float]
    expiry: Optional[str]
    kind: Optional[str]


def timestamp_parser(trading_date: str):
    year, month, day = (int(value) for value in trading_date.split("-"))
    midnight = int(datetime(year, month, day, tzinfo=timezone.utc).timestamp()) * NS

    def parse(value: str) -> int:
        hours = int(value[11:13])
        minutes = int(value[14:16])
        seconds = int(value[17:19])
        tail = value[19:]
        fraction = tail[1:].split("+", 1)[0].split("Z", 1)[0] if tail.startswith(".") else ""
        microseconds = int((fraction + "000000")[:6]) if fraction else 0
        return midnight + (hours * 3600 + minutes * 60 + seconds) * NS + microseconds * 1000

    return parse


def parse_instrument(
    instrument_id: str,
) -> tuple[str, Optional[str], Optional[float], Optional[str]]:
    parts = instrument_id.split(":")
    if len(parts) < 5 or parts[2] != "NIFTY":
        return "other", None, None, None
    if parts[3] == "future":
        return "future", parts[4], None, None
    if parts[3] == "option" and len(parts) >= 7:
        return "option", parts[4], float(parts[5]), parts[6]
    return "other", None, None, None


def quote_from_row(row: dict[str, Any], timestamp_ns: int) -> Optional[QuoteState]:
    bid = row.get("best_bid")
    ask = row.get("best_ask")
    bids = row.get("bids") or []
    asks = row.get("asks") or []
    if bid is None or ask is None or not bids or not asks:
        return None
    bid = float(bid)
    ask = float(ask)
    if not (bid > 0.0 and ask > bid):
        return None
    bid_quantity = sum(max(0.0, float(level.get("quantity") or 0.0)) for level in bids[:5])
    ask_quantity = sum(max(0.0, float(level.get("quantity") or 0.0)) for level in asks[:5])
    top_bid_quantity = max(0.0, float(bids[0].get("quantity") or 0.0))
    top_ask_quantity = max(0.0, float(asks[0].get("quantity") or 0.0))
    if bid_quantity + ask_quantity <= 0.0 or top_bid_quantity + top_ask_quantity <= 0.0:
        return None
    mid = (bid + ask) / 2.0
    half_spread = (ask - bid) / 2.0
    microprice = (ask * top_bid_quantity + bid * top_ask_quantity) / (
        top_bid_quantity + top_ask_quantity
    )
    instrument_type, expiry, strike, kind = parse_instrument(str(row.get("instrument_id", "")))
    if instrument_type == "other":
        return None
    return QuoteState(
        timestamp_ns=timestamp_ns,
        epoch=int(row.get("connection_epoch") or 0),
        mid=mid,
        bid=bid,
        ask=ask,
        relative_spread=(ask - bid) / mid,
        microprice_dislocation=(microprice - mid) / half_spread,
        depth_imbalance=(bid_quantity - ask_quantity) / (bid_quantity + ask_quantity),
        strike=strike,
        expiry=expiry,
        kind=kind,
    )


class StateBuilder:
    def __init__(self, near_expiry: str, far_expiry: str) -> None:
        self.expiry_bucket = {near_expiry: "near", far_expiry: "far"}
        self.quotes: dict[str, QuoteState] = {}
        self.future_ids: dict[str, str] = {}
        self.previous_option_mid: dict[str, float] = {}
        self.future_history: deque[tuple[int, float]] = deque()
        self.future_volume: deque[tuple[int, float]] = deque()
        self.current_epoch: Optional[int] = None
        self.block_until_ns = 0
        self.timestamps: list[int] = []
        self.values: list[list[float]] = []
        self.rejected_snapshots = 0
        self.epoch_transitions = 0

    def update(self, row: dict[str, Any], timestamp_ns: int) -> None:
        instrument_id = str(row.get("instrument_id", ""))
        instrument_type, expiry, _, _ = parse_instrument(instrument_id)
        epoch = int(row.get("connection_epoch") or 0)
        if self.current_epoch is None:
            self.current_epoch = epoch
        elif epoch != self.current_epoch:
            self.current_epoch = epoch
            self.block_until_ns = max(self.block_until_ns, timestamp_ns + POST_RECONNECT_BUFFER_NS)
            self.epoch_transitions += 1
        quote = quote_from_row(row, timestamp_ns)
        if quote is not None:
            self.quotes[instrument_id] = quote
            if instrument_type == "future" and expiry is not None:
                self.future_ids[expiry] = instrument_id
        if instrument_type == "future":
            increment = row.get("cumulative_volume_increment")
            if increment is not None and float(increment) > 0.0:
                self.future_volume.append((timestamp_ns, float(increment)))

    def selected_future(self) -> Optional[tuple[str, QuoteState]]:
        for expiry in sorted(self.future_ids):
            instrument_id = self.future_ids[expiry]
            quote = self.quotes.get(instrument_id)
            if quote is not None:
                return instrument_id, quote
        return None

    def snapshot(self, timestamp_ns: int) -> None:
        if timestamp_ns < self.block_until_ns:
            self.rejected_snapshots += 1
            return
        selected = self.selected_future()
        if selected is None:
            self.rejected_snapshots += 1
            return
        _, future = selected
        if timestamp_ns - future.timestamp_ns > MAX_QUOTE_AGE_NS:
            self.rejected_snapshots += 1
            return
        future_log_mid = math.log(future.mid)
        while self.future_history and self.future_history[0][0] < timestamp_ns - 30 * NS:
            self.future_history.popleft()
        history_values = [value for _, value in self.future_history] + [future_log_mid]
        if len(history_values) < 3:
            self.rejected_snapshots += 1
            self.future_history.append((timestamp_ns, future_log_mid))
            return
        future_returns = np.diff(np.asarray(history_values, dtype=np.float64))
        realized_volatility = float(np.sqrt(np.square(future_returns).sum()))
        previous_future = self.future_history[-1][1] if self.future_history else future_log_mid
        while self.future_volume and self.future_volume[0][0] < timestamp_ns - 10 * NS:
            self.future_volume.popleft()
        trade_intensity = math.log1p(sum(value for _, value in self.future_volume))

        grouped: dict[tuple[str, str], list[tuple[str, QuoteState, float]]] = {}
        for instrument_id, quote in self.quotes.items():
            bucket = self.expiry_bucket.get(quote.expiry or "")
            if bucket is None or quote.kind not in {"CE", "PE"} or quote.strike is None:
                continue
            if timestamp_ns - quote.timestamp_ns > MAX_QUOTE_AGE_NS:
                continue
            moneyness = abs(quote.strike / future.mid - 1.0)
            if moneyness <= MONEYNESS_LIMIT:
                grouped.setdefault((bucket, quote.kind), []).append(
                    (instrument_id, quote, moneyness)
                )
        incomplete = any(
            len(grouped.get((bucket, kind), [])) < 3
            for bucket in ("near", "far")
            for kind in ("CE", "PE")
        )
        if incomplete:
            self.rejected_snapshots += 1
            self.future_history.append((timestamp_ns, future_log_mid))
            return

        row_values: dict[str, float] = {
            "futures_log_mid": future_log_mid,
            "futures_relative_spread": future.relative_spread,
            "futures_microprice_dislocation": future.microprice_dislocation,
            "futures_depth_imbalance": future.depth_imbalance,
            "futures_log_trade_intensity_10s": trade_intensity,
            "futures_realized_volatility_30s": realized_volatility,
            "futures_return_5s": future_log_mid - previous_future,
        }
        current_option_mids: dict[str, float] = {}
        for (bucket, kind), items in grouped.items():
            aggregates: dict[str, list[float]] = {field: [] for field in AGGREGATE_FIELDS}
            for instrument_id, quote, _ in items:
                current_option_mids[instrument_id] = quote.mid
                previous_mid = self.previous_option_mid.get(instrument_id, quote.mid)
                aggregates["option_mid_to_future"].append(quote.mid / future.mid)
                aggregates["option_relative_spread"].append(quote.relative_spread)
                aggregates["option_microprice_dislocation"].append(quote.microprice_dislocation)
                aggregates["option_depth_imbalance"].append(quote.depth_imbalance)
                aggregates["option_return_5s"].append(math.log(quote.mid / previous_mid))
            for field, values in aggregates.items():
                row_values[f"{field}__{bucket}__{kind}"] = float(np.median(values))
            atm_id, atm_quote, _ = min(items, key=lambda item: item[2])
            del atm_id
            row_values[f"atm__option_mid_to_future__{bucket}__{kind}"] = atm_quote.mid / future.mid
            row_values[f"atm__option_relative_spread__{bucket}__{kind}"] = atm_quote.relative_spread
            row_values[f"atm__option_depth_imbalance__{bucket}__{kind}"] = atm_quote.depth_imbalance
        for bucket in ("near", "far"):
            call = row_values[f"atm__option_mid_to_future__{bucket}__CE"]
            put = row_values[f"atm__option_mid_to_future__{bucket}__PE"]
            row_values[f"atm_{bucket}_straddle_to_future"] = call + put
            row_values[f"atm_{bucket}_call_put_skew"] = call - put
            combined = grouped[(bucket, "CE")] + grouped[(bucket, "PE")]
            expiry_text = next(
                expiry
                for expiry, observed_bucket in self.expiry_bucket.items()
                if observed_bucket == bucket
            )
            expiry_timestamp = datetime.fromisoformat(expiry_text).replace(
                hour=10, tzinfo=timezone.utc
            )
            valuation_timestamp = datetime.fromtimestamp(timestamp_ns / NS, tz=timezone.utc)
            maturity_years = max(
                (expiry_timestamp - valuation_timestamp).total_seconds() / SECONDS_PER_YEAR,
                1.0 / SECONDS_PER_YEAR,
            )
            factors = fit_surface_factors(
                [
                    SurfaceQuote(
                        strike=float(quote.strike),
                        is_call=quote.kind == "CE",
                        bid=quote.bid,
                        ask=quote.ask,
                        depth_imbalance=quote.depth_imbalance,
                    )
                    for _, quote, _ in combined
                    if quote.strike is not None
                ],
                forward=future.mid,
                maturity_years=maturity_years,
                risk_free_rate=RISK_FREE_RATE,
                moneyness_limit=MONEYNESS_LIMIT,
            )
            if factors is None:
                self.rejected_snapshots += 1
                self.future_history.append((timestamp_ns, future_log_mid))
                return
            for field, value in zip(  # noqa: B905 - remote Python 3.9
                SURFACE_FACTOR_NAMES, factors.values()
            ):
                row_values[f"surface__{field}__{bucket}"] = value

            calls_by_strike = {
                quote.strike: quote for _, quote, _ in grouped[(bucket, "CE")]
            }
            puts_by_strike = {
                quote.strike: quote for _, quote, _ in grouped[(bucket, "PE")]
            }
            common_strikes = calls_by_strike.keys() & puts_by_strike.keys()
            if not common_strikes:
                self.rejected_snapshots += 1
                self.future_history.append((timestamp_ns, future_log_mid))
                return
            atm_strike = min(
                common_strikes,
                key=lambda strike: abs(float(strike) / future.mid - 1.0),
            )
            atm_call = calls_by_strike[atm_strike]
            atm_put = puts_by_strike[atm_strike]
            row_values[f"atm__strike__{bucket}"] = float(atm_strike)
            row_values[f"atm__straddle_bid_to_future__{bucket}"] = (
                atm_call.bid + atm_put.bid
            ) / future.mid
            row_values[f"atm__straddle_ask_to_future__{bucket}"] = (
                atm_call.ask + atm_put.ask
            ) / future.mid

        columns = output_columns()
        self.timestamps.append(timestamp_ns)
        self.values.append([row_values[column] for column in columns])
        self.previous_option_mid.update(current_option_mids)
        self.future_history.append((timestamp_ns, future_log_mid))


def rows_from(file: BinaryIO) -> Iterator[dict[str, Any]]:
    for line in file:
        if line.strip():
            yield orjson.loads(line)


def build(
    tape_path: Path,
    trading_date: str,
    near_expiry: str,
    far_expiry: str,
    max_rows: Optional[int],
) -> tuple[StateBuilder, dict[str, Any]]:
    parse_timestamp = timestamp_parser(trading_date)
    builder = StateBuilder(near_expiry, far_expiry)
    next_snapshot: Optional[int] = None
    rows = 0
    started = time.perf_counter()
    first_timestamp: Optional[int] = None
    last_timestamp: Optional[int] = None
    with tape_path.open("rb", buffering=8 * 1024 * 1024) as source:
        for row in rows_from(source):
            timestamp_ns = parse_timestamp(str(row["receive_ts"]))
            if first_timestamp is None:
                first_timestamp = timestamp_ns
                next_snapshot = (timestamp_ns // GRID_NS + 1) * GRID_NS
            assert next_snapshot is not None
            while next_snapshot <= timestamp_ns:
                builder.snapshot(next_snapshot)
                next_snapshot += GRID_NS
            builder.update(row, timestamp_ns)
            last_timestamp = timestamp_ns
            rows += 1
            if rows % 1_000_000 == 0:
                print(
                    json.dumps(
                        {
                            "rows": rows,
                            "states": len(builder.timestamps),
                            "elapsed_seconds": round(time.perf_counter() - started, 2),
                        }
                    ),
                    flush=True,
                )
            if max_rows is not None and rows >= max_rows:
                break
    metadata = {
        "tape_path": str(tape_path),
        "trading_date": trading_date,
        "near_expiry": near_expiry,
        "far_expiry": far_expiry,
        "rows_read": rows,
        "states": len(builder.timestamps),
        "rejected_snapshots": builder.rejected_snapshots,
        "epoch_transitions": builder.epoch_transitions,
        "first_receive_timestamp_ns": first_timestamp,
        "last_receive_timestamp_ns": last_timestamp,
        "elapsed_seconds": time.perf_counter() - started,
        "columns": output_columns(),
        "causal_quote_age_seconds": MAX_QUOTE_AGE_NS / NS,
        "post_reconnect_buffer_seconds": POST_RECONNECT_BUFFER_NS / NS,
        "moneyness_limit": MONEYNESS_LIMIT,
    }
    return builder, metadata


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tape", type=Path)
    parser.add_argument("--trading-date", required=True)
    parser.add_argument("--near-expiry", required=True)
    parser.add_argument("--far-expiry", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-rows", type=int)
    args = parser.parse_args()
    builder, metadata = build(
        args.tape,
        args.trading_date,
        args.near_expiry,
        args.far_expiry,
        args.max_rows,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    values = np.asarray(builder.values, dtype=np.float32)
    if len(values) < 10:
        raise ValueError(f"only {len(values)} usable market states were constructed")
    np.savez_compressed(
        args.output,
        timestamps=np.asarray(builder.timestamps, dtype=np.int64),
        values=values,
        columns=np.asarray(output_columns()),
        trading_date=np.asarray([args.trading_date]),
    )
    args.output.with_suffix(".metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(metadata, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
