#!/usr/bin/env python3
"""Measure `TOUCH-01` and `TOUCH-02` on one read-only tape — `D38 / TOUCH-METRICS-2026-08-20`.

`TOUCH-01` is a factual measurement.  It classifies every observed print against the displayed
level one the capture-time DAT-14 classifier already aligned to it, and reports the distribution
overall, by hour and by displayed-spread bucket.  It is reported exactly as measured, whether or
not it supports the hypothesis that motivated the specification.

`TOUCH-02` reports, at every declared rolling window, how often the effective touch is even
defined and how stale it is when it is.  A reference price that is undefined at most anchors is
not a usable reference price, and that has to be visible before any result computed under it is
read.

The tape is opened read-only and never written.  Nothing here fits a model or scores a predictor.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shaurya.signals.effective_touch import (
    EFFECTIVE_TOUCH_WINDOWS_SECONDS,
    PRIMARY_EFFECTIVE_TOUCH_WINDOW,
    EffectiveTouchSeries,
    build_trade_prints,
    effective_touch_coverage,
    effective_touch_metadata,
    print_location_diagnostics,
)

SCAN_ID = "X-TOUCH-METRICS-2026-08-20"
SPECIFICATION_ID = "D38 / TOUCH-METRICS-2026-08-20"
CONFIRMATORY_ELIGIBLE = False

#: Only ``full`` packets carry a print.  Pre-filtering on the raw bytes avoids decoding the
#: depth200 rows, which are two orders of magnitude larger and irrelevant to this measurement.
FULL_MARKER = b'"event_type":"full"'


def iter_full_rows(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("rb") as handle:
        for raw in handle:
            if FULL_MARKER in raw:
                yield json.loads(raw)


def build_report(path: Path, *, anchor_stride: int) -> dict[str, Any]:
    rows = list(iter_full_rows(path))
    series = build_trade_prints(rows)
    location = print_location_diagnostics(series)
    anchors = [item.receive_ts_ns for item in series.prints][::anchor_stride]
    coverage = [
        effective_touch_coverage(
            EffectiveTouchSeries(series.prints, window_seconds=window), anchors
        )
        for window in EFFECTIVE_TOUCH_WINDOWS_SECONDS
    ]
    return {
        "scan_id": SCAN_ID,
        "specification_id": SPECIFICATION_ID,
        "confirmatory_eligible": CONFIRMATORY_ELIGIBLE,
        "evidence_level": "exploratory measurement on one tape; no estimator is fitted",
        "tape": str(path),
        "full_packets": len(rows),
        "touch_01_print_locations": location,
        "touch_02_effective_touch": {
            "metadata": effective_touch_metadata(),
            "anchor_stride_prints": anchor_stride,
            "anchors": len(anchors),
            "primary_window_seconds": PRIMARY_EFFECTIVE_TOUCH_WINDOW,
            "by_window": coverage,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tape", type=Path, required=True, help="read-only JSONL tape")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--anchor-stride",
        type=int,
        default=1,
        help="evaluate the effective touch at every Nth print rather than at all of them",
    )
    args = parser.parse_args()
    if args.anchor_stride < 1:
        raise ValueError("anchor stride must be positive")
    report = build_report(args.tape, anchor_stride=args.anchor_stride)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    overall = report["touch_01_print_locations"]["overall"]
    print(
        json.dumps(
            {
                "tape": str(args.tape),
                "prints_classified": overall["n"],
                "inside_share": overall["inside_share"],
                "at_touch_share": overall["at_touch_share"],
                "outside_share": overall["outside_share"],
                "median_displayed_spread_ticks": report["touch_01_print_locations"][
                    "displayed_spread_ticks"
                ]["p50"],
                "effective_touch_coverage_by_window": {
                    row["window_seconds"]: row["coverage"]
                    for row in report["touch_02_effective_touch"]["by_window"]
                },
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
