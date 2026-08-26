#!/usr/bin/env python3
"""Run the D40 displayed-mid OFI horizon extension on the immutable 2026-08-20 tape."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.d39_fixed_target_panel import _git_commit, _write_atomic
from scripts.ofi_horserace import build_tape_input
from shaurya.analytics.ofi_live_partial import iter_late_partial_rows
from shaurya.signals.deep_book_normal_activity import EMBARGO_SECONDS
from shaurya.signals.deep_book_ofi import CAUSAL_GAP_SECONDS
from shaurya.signals.effective_touch import build_trade_prints
from shaurya.signals.fixed_target_panel import build_fixed_target_panel

SCAN_ID = "X-D40-OFI-HORIZON-EXTENSION-2026-08-20"
SPECIFICATION_ID = "D40 / OFI-HORIZON-EXTENSION-2026-08-20"
DESIGN_DOCUMENT = "research/docs/D40-OFI-HORIZON-EXTENSION-SPEC-2026-08-20.md"
HORIZONS_SECONDS = (10.0, 20.0, 30.0, 45.0, 60.0, 90.0, 120.0)
REFERENCE_PRICE = "displayed_mid"
LEVELS = 10
WINDOW_SECONDS = 10.0
COMPETITOR = "C8"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _c8_summary(artifact: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for cell in artifact["cells"]:
        if (
            cell["reference_price"] != REFERENCE_PRICE
            or int(cell["levels"]) != LEVELS
            or float(cell["h1_seconds"]) != WINDOW_SECONDS
        ):
            raise RuntimeError(f"D40 cell changed the fixed model object: {cell}")
        if cell["status"] != "estimated":
            raise RuntimeError(f"D40 cell is not estimable: {cell}")
        estimated = {
            row["competitor"]: row
            for row in cell["competitors"]
            if row.get("status") == "estimated"
        }
        c8 = estimated[COMPETITOR]
        r2 = c8["absolute_oos_r2"]
        if r2 is None:
            raise RuntimeError(f"D40 {cell['h2_seconds']} second C8 R2 is missing")
        rows.append(
            {
                "horizon_seconds": float(cell["h2_seconds"]),
                "absolute_oos_r2": float(r2),
                "absolute_oos_r2_percent": 100.0 * float(r2),
                "train_n": int(cell["train_n"]),
                "test_n": int(cell["test_n"]),
                "common_test_row_hash": cell["common_test_row_hash"],
                "selected_ridge_alpha": c8["selected_alpha"],
            }
        )
    rows.sort(key=lambda row: row["horizon_seconds"])
    if tuple(row["horizon_seconds"] for row in rows) != HORIZONS_SECONDS:
        raise RuntimeError("D40 did not emit the complete frozen seven-horizon grid")
    values = [row["absolute_oos_r2"] for row in rows]
    strictly_increasing = all(right > left for left, right in zip(values, values[1:], strict=False))
    nondecreasing = all(right >= left for left, right in zip(values, values[1:], strict=False))
    peak = max(rows, key=lambda row: row["absolute_oos_r2"])
    first_decline = next(
        (
            rows[index]["horizon_seconds"]
            for index in range(1, len(rows))
            if rows[index]["absolute_oos_r2"] < rows[index - 1]["absolute_oos_r2"]
        ),
        None,
    )
    return {
        "schema_version": 1,
        "scan_id": SCAN_ID,
        "specification_id": SPECIFICATION_ID,
        "design_document": DESIGN_DOCUMENT,
        "sample_role": artifact["sample_role"],
        "confirmatory_eligible": False,
        "registered_replication_eligible": False,
        "order_entry_enabled": False,
        "source_tape": artifact["source_tape"],
        "source_tape_sha256": artifact["tape"]["sha256"],
        "code_commit": artifact["code_commit"],
        "target": "displayed-mid return from t+0.5s to t+0.5s+horizon",
        "model": (
            "C8: spread and log1p level-one depth controls plus ten depth-scaled, "
            "rank-keyed CCZ OFI levels accumulated over (t-10s,t]"
        ),
        "split": artifact["split"],
        "rows": rows,
        "strictly_increasing": strictly_increasing,
        "nondecreasing": nondecreasing,
        "peak_horizon_seconds": peak["horizon_seconds"],
        "peak_absolute_oos_r2": peak["absolute_oos_r2"],
        "first_decline_horizon_seconds": first_decline,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tape", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    parser.add_argument("--progress-output", type=Path)
    parser.add_argument("--replicates", type=int, default=399)
    parser.add_argument("--seed", type=int, default=20260820)
    args = parser.parse_args()
    if args.replicates < 0:
        raise ValueError("replicates cannot be negative")

    tape = build_tape_input(
        args.tape,
        tape_index=0,
        late_partial_exploratory=True,
        level_counts=(LEVELS,),
        response_horizons=HORIZONS_SECONDS,
    )
    full_rows = [
        row for row in iter_late_partial_rows(args.tape) if row.get("event_type") == "full"
    ]
    prints = build_trade_prints(full_rows)

    progress_handle = None
    if args.progress_output is not None:
        args.progress_output.parent.mkdir(parents=True, exist_ok=True)
        progress_handle = args.progress_output.open("a", encoding="utf-8")

    def progress(event: dict[str, Any]) -> None:
        print(json.dumps(event, sort_keys=True), flush=True)
        if progress_handle is not None:
            progress_handle.write(json.dumps(event, sort_keys=True) + "\n")
            progress_handle.flush()

    embargo_seconds = max(EMBARGO_SECONDS, CAUSAL_GAP_SECONDS + max(HORIZONS_SECONDS))
    try:
        artifact = build_fixed_target_panel(
            tape,
            prints=prints.prints,
            references=(REFERENCE_PRICE,),
            levels=(LEVELS,),
            windows=(WINDOW_SECONDS,),
            horizons=HORIZONS_SECONDS,
            replicates=args.replicates,
            seed=args.seed,
            embargo_seconds=embargo_seconds,
            progress=progress,
        )
    finally:
        if progress_handle is not None:
            progress_handle.close()

    artifact.update(
        {
            "scan_id": SCAN_ID,
            "specification_id": SPECIFICATION_ID,
            "design_document": DESIGN_DOCUMENT,
            "code_commit": _git_commit(),
            "source_tape": str(args.tape),
            "extension_of": "D39 / FIXED-TARGET-COMPETITOR-PANEL",
            "reported_object": COMPETITOR,
        }
    )
    _write_atomic(args.output, artifact)
    summary = _c8_summary(artifact)
    summary["full_artifact_sha256"] = _sha256(args.output)
    _write_atomic(args.summary_output, summary)
    print(
        json.dumps(
            {
                "status": "complete",
                "output": str(args.output),
                "summary_output": str(args.summary_output),
                "full_artifact_sha256": summary["full_artifact_sha256"],
                "cells": len(artifact["cells"]),
                "strictly_increasing": summary["strictly_increasing"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
