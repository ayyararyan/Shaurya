#!/usr/bin/env python3
"""SIG-21 exploratory future-midpoint response scan `X-SIG21-DAT20-01` over the DAT-20 tapes.

Reproducible entry point that attaches the registered `H-SIG21` response convention to the
already-registered outcome-blind construction detector's candidates, over the two retained
`DAT-20` NIFTY-futures tapes only.

**This cannot produce a SIG-21 result and refuses to pretend otherwise.** Both tapes were
captured before the registering commit `f2cf6501` was pushed, so under `H-SIG21` §1.5 they were
already permanently ineligible for the first outcome sample and under §1.2 their price paths were
already excluded from SIG-21 inference. The scan therefore carries `confirmatory_eligible: false`,
labels every magnitude cutoff `in_sample_exploratory`, refuses any tape outside the two pinned
SHA-256s, and refuses any request phrased as a confirmatory or economic claim.

Run:

    .venv/bin/python scripts/sig21_exploratory_response_scan.py \
      --tape data/live-captures/dat20-nifty-three-tier/<run-1>/tape_<run-1>.jsonl \
      --tape data/live-captures/dat20-nifty-three-tier/<run-2>/tape_<run-2>.jsonl \
      --output artifacts/sig21-exploratory-response/sig21_exploratory_response_2026-08-19.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sig21_construction_replay import (
    capture_metrics_for,
    iter_tape_rows,
    manifest_sha256_for,
    sha256_file,
    verify_instrument,
)
from shaurya.data.depth_thinning_analysis import DEPTH20, DEPTH200, build_states
from shaurya.signals.deep_book_anomaly import detect_candidates
from shaurya.signals.deep_book_construction_grid import (
    NANOSECONDS_PER_SECOND,
    edge_distance,
    outer_price,
)
from shaurya.signals.deep_book_exploratory_response import (
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    CONFIRMATORY_ELIGIBLE,
    EXPLORATORY_SCAN_ID,
    SELECTIVITY_GRID,
    SELECTIVITY_GRID_FINE,
    ConfirmatoryUseRefused,
    TapeNotPermitted,
    TapeScan,
    assert_exploratory_claim,
    assert_permitted_tape,
    attach_burst_responses,
    attach_past_return_placebo,
    build_control_instants,
    build_covariate_series,
    build_exploratory_artifact,
    family_rows,
)

SESSION_ID = "2026-08-19"


def code_commit() -> str | None:
    """The current repository commit, recorded in the artifact so the run is reproducible."""

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def build_scan(tape: Path, *, tape_index: int) -> tuple[TapeScan, dict[int, Any]]:
    """Replay one permitted tape into a complete scan input, responses included."""

    metrics = capture_metrics_for(tape)
    run_id, instrument_id, _, _ = verify_instrument(metrics, tape)
    computed = sha256_file(tape)
    recorded = manifest_sha256_for(tape)
    if recorded is not None and recorded != computed:
        raise ValueError(
            f"{tape} SHA-256 {computed} does not match the manifest value {recorded}; the "
            "retained tape has changed since capture and must not be replayed."
        )
    assert_permitted_tape(run_id=run_id, tape_sha256=computed)

    rows = list(iter_tape_rows(tape))
    depth200 = build_states(rows, DEPTH200)
    depth20 = build_states(rows, DEPTH20)
    candidates = []
    edges: list[float | None] = []
    for previous, current in zip(depth200, depth200[1:], strict=False):
        result = detect_candidates(previous, current, instrument_id=instrument_id)
        for candidate in result.candidates:
            side = "bid" if candidate.side == "bid" else "ask"
            edges.append(
                edge_distance(
                    candidate,
                    outer_price(previous, side),
                    outer_price(current, side),
                )
            )
        candidates.extend(result.candidates)

    burst_timestamps = sorted({candidate.receive_ts_ns for candidate in candidates})
    responses, failures = attach_burst_responses(
        burst_timestamps,
        depth20,
        tape_index=tape_index,
        run_id=run_id,
    )
    series = build_covariate_series(
        depth20,
        run_id=run_id,
        session_id=SESSION_ID,
        instrument_id=instrument_id,
    )
    controls = build_control_instants(depth20, series, tape_index=tape_index, run_id=run_id)
    observed_seconds = (
        (depth200[-1].receive_ts_ns - depth200[0].receive_ts_ns) / NANOSECONDS_PER_SECOND
        if len(depth200) > 1
        else 0.0
    )
    scan = TapeScan(
        tape_index=tape_index,
        run_id=run_id,
        session_id=SESSION_ID,
        instrument_id=instrument_id,
        tape_sha256=computed,
        candidates=tuple(candidates),
        edge_distances=tuple(edges),
        responses_by_ts={response.receive_ts_ns: response for response in responses},
        control_instants=controls,
        covariates=series,
        observed_seconds=observed_seconds,
        label_failures=dict(failures),
    )
    return scan, attach_past_return_placebo(burst_timestamps, depth20)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tape",
        required=True,
        action="append",
        type=Path,
        help="Retained pre-registration DAT-20 tape JSONL (repeatable).",
    )
    parser.add_argument("--output", required=True, type=Path, help="Artifact JSON path.")
    parser.add_argument(
        "--family-rows-output",
        type=Path,
        default=None,
        help="Optional JSONL path for one flattened row per family cell per arm.",
    )
    parser.add_argument(
        "--replicates",
        type=int,
        default=BOOTSTRAP_REPLICATES,
        help="Stationary block bootstrap replicates for the Romano-Wolf step-down.",
    )
    parser.add_argument("--seed", type=int, default=BOOTSTRAP_SEED, help="Bootstrap seed.")
    parser.add_argument(
        "--fine-selectivity",
        action="store_true",
        help="Add extra selectivity points bracketing the registered 99.5%%/99.9%% thresholds.",
    )
    parser.add_argument(
        "--claim",
        action="append",
        default=None,
        help=(
            "Optional named claim this run is being asked to support. Any confirmatory or "
            f"economic claim is refused: {EXPLORATORY_SCAN_ID} has "
            f"confirmatory_eligible={CONFIRMATORY_ELIGIBLE}."
        ),
    )
    return parser


def _write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)


def run(args: argparse.Namespace) -> dict[str, Any]:
    # Refused before any tape is opened, so a forbidden framing cannot even read the input.
    assert_exploratory_claim(list(args.claim or ()))
    cutoffs = tuple(SELECTIVITY_GRID)
    if args.fine_selectivity:
        cutoffs = tuple(sorted(set(cutoffs) | set(SELECTIVITY_GRID_FINE)))
    scans = []
    past_returns: dict[tuple[int, int], Any] = {}
    for tape_index, tape in enumerate(args.tape):
        scan, past = build_scan(tape, tape_index=tape_index)
        scans.append(scan)
        for stamp, row in past.items():
            past_returns[(tape_index, stamp)] = row
    return build_exploratory_artifact(
        scans,
        past_returns=past_returns,
        code_commit=code_commit(),
        replicates=args.replicates,
        seed=args.seed,
        cutoffs=cutoffs,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        artifact = run(args)
    except (ConfirmatoryUseRefused, TapeNotPermitted) as error:
        print(json.dumps({"status": "refused", "reason": str(error)}))
        return 2
    _write(args.output, json.dumps(artifact, indent=2, sort_keys=True, default=str) + "\n")
    if args.family_rows_output is not None:
        rows = family_rows(artifact)
        _write(
            args.family_rows_output,
            "".join(json.dumps(row, sort_keys=True, default=str) + "\n" for row in rows),
        )
    print(
        json.dumps(
            {
                "status": "ok",
                "exploratory_scan_id": artifact["protocol"]["exploratory_scan_id"],
                "confirmatory_eligible": artifact["protocol"]["confirmatory_eligible"],
                "output": str(args.output),
                "candidates": artifact["totals"]["candidates"],
                "family_cells": len(artifact["family"]["cells"]),
                "max_episode_count": artifact["selectivity_curve"]["max_episode_count"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
