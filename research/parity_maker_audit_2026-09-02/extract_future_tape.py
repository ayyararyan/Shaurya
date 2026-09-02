#!/usr/bin/env python3
"""Stream a Shaurya raw tape and retain only valid NIFTY futures books."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

import numpy as np


def timestamp_ns(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp() * 1_000_000_000)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tape", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows: list[tuple[object, ...]] = []
    scanned = 0
    matched = 0
    with args.tape.open("rb", buffering=8 * 1024 * 1024) as handle:
        for raw in handle:
            scanned += 1
            if b":future:" not in raw:
                continue
            event = json.loads(raw)
            if event.get("event_type") != "full" or not event.get("receive_ts"):
                continue
            bid = event.get("best_bid")
            ask = event.get("best_ask")
            bids = event.get("bids") or []
            asks = event.get("asks") or []
            if bid is None or ask is None or not bids or not asks or float(ask) <= float(bid):
                continue
            matched += 1
            rows.append(
                (
                    timestamp_ns(event["receive_ts"]),
                    float(bid),
                    float(ask),
                    float(bids[0].get("quantity") or 0),
                    float(asks[0].get("quantity") or 0),
                    float(event["last_price"]) if event.get("last_price") is not None else np.nan,
                    float(event["last_quantity"]) if event.get("last_quantity") is not None else np.nan,
                    float(event["cumulative_volume"]) if event.get("cumulative_volume") is not None else np.nan,
                )
            )
    rows.sort(key=lambda row: row[0])
    values = np.asarray(rows, dtype=np.float64)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.out,
        timestamps=values[:, 0].astype(np.int64),
        bid=values[:, 1], ask=values[:, 2], bid_quantity=values[:, 3],
        ask_quantity=values[:, 4], last_price=values[:, 5],
        last_quantity=values[:, 6], cumulative_volume=values[:, 7],
    )
    print(json.dumps({
        "source": str(args.tape), "scanned_rows": scanned, "future_books": matched,
        "first_timestamp_ns": int(values[0, 0]), "last_timestamp_ns": int(values[-1, 0]),
    }))


if __name__ == "__main__":
    main()
