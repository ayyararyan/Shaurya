#!/usr/bin/env python3
"""DAT-17: measure receive-timestamp cadence and book-state changes in JSONL tapes."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path
from statistics import fmean
from typing import Any


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tape", type=Path)
    parser.add_argument("--event-type", required=True)
    parser.add_argument("--gap-bin-ms", type=float, default=50.0)
    parser.add_argument("--output", type=Path)
    return parser


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _level_tuple(row: dict[str, Any], side: str, limit: int | None = None) -> tuple[Any, ...]:
    levels = row.get(side) or []
    selected = levels if limit is None else levels[:limit]
    return tuple(
        (level.get("price"), level.get("quantity"), level.get("orders")) for level in selected
    )


def _top_price(row: dict[str, Any]) -> tuple[Any, Any]:
    return row.get("best_bid"), row.get("best_ask")


def _top_fields(row: dict[str, Any]) -> tuple[Any, ...]:
    return _level_tuple(row, "bids", 1) + _level_tuple(row, "asks", 1)


def _book_fingerprint(row: dict[str, Any]) -> tuple[Any, ...]:
    return _level_tuple(row, "bids") + ("ASK",) + _level_tuple(row, "asks")


def analyse_tape(tape: Path, event_type: str, gap_bin_ms: float) -> dict[str, Any]:
    if gap_bin_ms <= 0:
        raise ValueError("gap-bin-ms must be positive")
    bursts: OrderedDict[str, dict[str, Any]] = OrderedDict()
    rows = 0
    five_by_five_rows = 0
    with tape.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            row = json.loads(line)
            if row.get("event_type") != event_type:
                continue
            receive_ts = row.get("receive_ts")
            if not isinstance(receive_ts, str):
                raise ValueError(f"line {line_number}: missing string receive_ts")
            datetime.fromisoformat(receive_ts)
            rows += 1
            if len(row.get("bids") or []) >= 5 and len(row.get("asks") or []) >= 5:
                five_by_five_rows += 1
            if receive_ts not in bursts:
                bursts[receive_ts] = {"row_count": 0, "final_row": row}
            bursts[receive_ts]["row_count"] += 1
            bursts[receive_ts]["final_row"] = row

    if len(bursts) < 2:
        raise ValueError(f"need at least two {event_type!r} receive timestamps")
    timestamps = [datetime.fromisoformat(value) for value in bursts]
    if timestamps != sorted(timestamps):
        raise ValueError("receive timestamps are not non-decreasing")
    gaps_ms = [
        (later - earlier).total_seconds() * 1_000.0
        for earlier, later in zip(timestamps, timestamps[1:], strict=True)
    ]
    row_counts = [int(value["row_count"]) for value in bursts.values()]
    states = [value["final_row"] for value in bursts.values()]
    transition_count = len(states) - 1
    price_changes = sum(
        _top_price(previous) != _top_price(current)
        for previous, current in zip(states, states[1:], strict=True)
    )
    top_field_changes = sum(
        _top_fields(previous) != _top_fields(current)
        for previous, current in zip(states, states[1:], strict=True)
    )
    book_changes = sum(
        _book_fingerprint(previous) != _book_fingerprint(current)
        for previous, current in zip(states, states[1:], strict=True)
    )
    bins = Counter(math.floor(value / gap_bin_ms) for value in gaps_ms)
    modal_index, modal_count = min(bins.items(), key=lambda item: (-item[1], item[0]))
    span_seconds = (timestamps[-1] - timestamps[0]).total_seconds()
    return {
        "task": "DAT-17",
        "source_tape": str(tape),
        "event_type": event_type,
        "first_receive_ts": timestamps[0].isoformat(),
        "last_receive_ts": timestamps[-1].isoformat(),
        "event_span_seconds": span_seconds,
        "rows": rows,
        "rows_with_at_least_5_bid_and_5_ask_levels": five_by_five_rows,
        "distinct_receive_timestamps": len(bursts),
        "transition_count": transition_count,
        "transition_rate_per_second": transition_count / span_seconds,
        "rows_per_burst": {
            "mean": fmean(row_counts),
            "min": min(row_counts),
            "p50": _percentile([float(value) for value in row_counts], 0.50),
            "max": max(row_counts),
        },
        "gap_ms": {
            "min": min(gaps_ms),
            "p05": _percentile(gaps_ms, 0.05),
            "p50": _percentile(gaps_ms, 0.50),
            "p95": _percentile(gaps_ms, 0.95),
            "max": max(gaps_ms),
        },
        "modal_gap_bin_ms": {
            "lower_inclusive": modal_index * gap_bin_ms,
            "upper_exclusive": (modal_index + 1) * gap_bin_ms,
            "count": modal_count,
            "fraction_of_gaps": modal_count / len(gaps_ms),
        },
        "top_of_book_price_changes": {
            "count": price_changes,
            "denominator_transitions": transition_count,
            "fraction": price_changes / transition_count,
            "rate_per_second": price_changes / span_seconds,
        },
        "top_of_book_any_field_changes": {
            "count": top_field_changes,
            "denominator_transitions": transition_count,
            "fraction": top_field_changes / transition_count,
            "rate_per_second": top_field_changes / span_seconds,
        },
        "full_book_changes": {
            "count": book_changes,
            "denominator_transitions": transition_count,
            "fraction": book_changes / transition_count,
            "rate_per_second": book_changes / span_seconds,
        },
    }


def main() -> int:
    args = _parser().parse_args()
    result = analyse_tape(args.tape, args.event_type, args.gap_bin_ms)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
