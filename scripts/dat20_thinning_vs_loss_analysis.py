#!/usr/bin/env python3
"""DAT-20 analysis: is depth200's skip pattern activity thinning, or feed loss?

Reproducible entry point for the four pre-registered measurements in
`docs/live-evidence/DAT-20-2026-08-19.md` §1.7. Consumes retained DAT-20 tapes and emits one
JSON result document. No live connection is opened.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from shaurya.data.depth_thinning_analysis import (
    DEPTH20,
    DEPTH200,
    FULL,
    PHASE_TOLERANCES_MS,
    SKIP_GAP_THRESHOLD_MS,
    STRICT_STALENESS_BOUND_MS,
    agreement_pass,
    build_states,
    change_rate_by_level,
    crossing_level,
    occupancy_and_span,
    percentile,
    skip_window_test,
    spearman,
)

# Measured cadences carried forward from DAT-16/DAT-17 as reference thresholds only. These are
# prior verified evidence, not DAT-20 results, and are not re-derived here.
DEPTH20_CADENCE_PER_SECOND = 2.00
FULL_CADENCE_LOW_PER_SECOND = 1.2
FULL_CADENCE_HIGH_PER_SECOND = 1.7


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tape", required=True, action="append", type=Path, help="Retained tape JSONL (repeatable)."
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--levels-vs-depth20",
        type=int,
        default=20,
        help="Levels compared between depth200 and depth20.",
    )
    parser.add_argument(
        "--levels-vs-full",
        type=int,
        default=5,
        help="Levels compared between depth200 and the Full packet's 5-level block.",
    )
    parser.add_argument("--change-rate-levels", type=int, default=200)
    return parser


def _load(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def _cadence(states: list[Any]) -> dict[str, Any]:
    gaps = [
        (later.receive_ts_ns - earlier.receive_ts_ns) / 1_000_000
        for earlier, later in zip(states, states[1:], strict=False)
    ]
    if not gaps:
        return {"states": len(states), "note": "insufficient states"}
    span = (states[-1].receive_ts_ns - states[0].receive_ts_ns) / 1_000_000_000
    return {
        "states": len(states),
        "gaps": len(gaps),
        "span_seconds": span,
        "rate_per_second": len(gaps) / span if span else None,
        "gap_min_ms": min(gaps),
        "gap_p05_ms": percentile(gaps, 0.05),
        "gap_p50_ms": percentile(gaps, 0.50),
        "gap_p95_ms": percentile(gaps, 0.95),
        "gap_max_ms": max(gaps),
        "gaps_over_skip_threshold": sum(1 for gap in gaps if gap > SKIP_GAP_THRESHOLD_MS),
    }


def _band_shares(per_level: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum(entry["changed_publications"] for entry in per_level)
    if total == 0:
        return {"note": "no changes observed"}

    def share(low: int, high: int) -> float:
        return (
            sum(
                entry["changed_publications"]
                for entry in per_level
                if low <= entry["level"] <= high
            )
            / total
        )

    return {
        "total_level_change_events": total,
        "share_levels_1_to_5_reachable_by_full": share(1, 5),
        "share_levels_1_to_20_reachable_by_depth20": share(1, 20),
        "share_levels_21_to_200_only_depth200": share(21, len(per_level)),
        "share_levels_21_to_50": share(21, 50),
        "share_levels_51_to_100": share(51, 100),
        "share_levels_101_to_200": share(101, 200),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    rows = _load(args.tape)
    depth200 = build_states(rows, DEPTH200)
    depth20 = build_states(rows, DEPTH20)
    full = build_states(rows, FULL)

    result: dict[str, Any] = {
        "task": "DAT-20",
        "object": "depth200 activity thinning versus feed loss (H-DAT20)",
        "tapes": [str(path) for path in args.tape],
        "rows_loaded": len(rows),
        "pre_registered_thresholds": {
            "skip_gap_threshold_ms": SKIP_GAP_THRESHOLD_MS,
            "strict_staleness_bound_ms": STRICT_STALENESS_BOUND_MS,
            "phase_tolerances_ms": list(PHASE_TOLERANCES_MS),
        },
        "reference_cadences_from_dat16_dat17": {
            "depth20_publications_per_second": DEPTH20_CADENCE_PER_SECOND,
            "full_updates_per_second_low": FULL_CADENCE_LOW_PER_SECOND,
            "full_updates_per_second_high": FULL_CADENCE_HIGH_PER_SECOND,
        },
        "cadence_observed_this_run": {
            "depth200": _cadence(depth200),
            "depth20": _cadence(depth20),
            "full": _cadence(full),
        },
    }

    # Measurement 1 — cross-tier agreement, both directions.
    result["measurement_1_cross_tier_agreement"] = {
        "depth200_vs_depth20_forward": agreement_pass(
            depth20, depth200, args.levels_vs_depth20, label="witness=depth20, comparand=depth200"
        ),
        "depth200_vs_full_forward": agreement_pass(
            full, depth200, args.levels_vs_full, label="witness=full, comparand=depth200"
        ),
        "pass_c_reverse_depth200_witness_vs_depth20": agreement_pass(
            depth200, depth20, args.levels_vs_depth20, label="witness=depth200, comparand=depth20"
        ),
        "pass_c_reverse_depth200_witness_vs_full": agreement_pass(
            depth200, full, args.levels_vs_full, label="witness=depth200, comparand=full"
        ),
    }

    # Measurement 2 — change rate by level index.
    measurement_2: dict[str, Any] = {}
    for side in ("bid", "ask"):
        curve = change_rate_by_level(rows, side, levels=args.change_rate_levels)
        per_level = curve.get("per_level")
        if per_level:
            rates = [entry["change_rate_per_second"] for entry in per_level]
            curve["spearman_level_index_vs_change_rate"] = spearman(rates)
            curve["crossing_levels"] = {
                "below_depth20_cadence_2_00_per_second": crossing_level(
                    per_level, DEPTH20_CADENCE_PER_SECOND
                ),
                "below_full_cadence_1_7_per_second": crossing_level(
                    per_level, FULL_CADENCE_HIGH_PER_SECOND
                ),
                "below_full_cadence_1_2_per_second": crossing_level(
                    per_level, FULL_CADENCE_LOW_PER_SECOND
                ),
                "below_0_10_per_second": crossing_level(per_level, 0.10),
                "below_0_01_per_second": crossing_level(per_level, 0.01),
            }
            curve["change_event_band_shares"] = _band_shares(per_level)
        measurement_2[side] = curve
    result["measurement_2_change_rate_by_level"] = measurement_2

    # Measurement 3 — skip explanation.
    result["measurement_3_skip_explanation"] = {
        "full_witness_top5_price": skip_window_test(
            depth200, full, args.levels_vs_full, "all_levels_price_equal"
        ),
        "full_witness_top5_all_fields": skip_window_test(
            depth200, full, args.levels_vs_full, "all_levels_all_fields_equal"
        ),
        "full_witness_level1_price": skip_window_test(
            depth200, full, args.levels_vs_full, "level1_price_equal"
        ),
        "depth20_witness_top20_price": skip_window_test(
            depth200, depth20, args.levels_vs_depth20, "all_levels_price_equal"
        ),
        "depth20_witness_level1_price": skip_window_test(
            depth200, depth20, args.levels_vs_depth20, "level1_price_equal"
        ),
    }

    # Measurement 4 — occupancy and price span.
    result["measurement_4_occupancy_and_span"] = {
        "depth200": occupancy_and_span(depth200),
        "depth20": occupancy_and_span(depth20),
    }
    return result


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(result, indent=2, sort_keys=True, default=str) + "\n"
    descriptor = os.open(args.output, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(encoded)
    print(json.dumps({"status": "ok", "output": str(args.output), "rows": result["rows_loaded"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
