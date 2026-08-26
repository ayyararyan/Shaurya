#!/usr/bin/env python3
"""Ordinary deep-book activity vs the futures price — exploratory scan `X-DEEPBOOK-DAT20-02`.

Reproducible entry point for the question Aryan asked on 2026-08-19: *"what does normal order
book activity tell us about predictive power of the futures at 200 levels?"*

**No anomalies.** No thresholds, no rare-tail selection, no episodes, no anomaly detector. Just
the ordinary state and flow of the 200-level book at every depth200 publication, and what it says
about the next depth20 mid-price move.

**This is not `H-SIG21`.** It shares two source tapes and the mid-price target convention with
that registration and nothing else. `H-SIG21`'s 384-cell family is untouched.

**It can never be confirmatory.** Both tapes predate the `H-SIG21` registering commit `f2cf6501`,
so they were already permanently outside any confirmatory sample. The scan carries
`confirmatory_eligible: false`, refuses a confirmatory or economic framing before it opens a file,
and refuses any tape outside the two pinned SHA-256s.

Run:

    .venv/bin/python -m scripts.deepbook_normal_activity_scan \
      --tape data/live-captures/dat20-nifty-three-tier/<run-1>/tape_<run-1>.jsonl \
      --tape data/live-captures/dat20-nifty-three-tier/<run-2>/tape_<run-2>.jsonl \
      --output artifacts/deepbook-normal-activity/deepbook_normal_activity_2026-08-19.json
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
from shaurya.analytics.depth_thinning_analysis import DEPTH20, DEPTH200, build_states
from shaurya.signals.deep_book_normal_activity import (
    BLOCK_BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    CONFIRMATORY_ELIGIBLE,
    EXPLORATORY_SCAN_ID,
    HORIZONS_SECONDS,
    ConfirmatoryUseRefused,
    TapeInput,
    TapeNotPermitted,
    assert_exploratory_claim,
    assert_permitted_tape,
    association_rows,
    build_normal_activity_artifact,
    build_observations,
    nested_rows,
)
from shaurya.signals.deep_book_response import NANOSECONDS_PER_SECOND


def code_commit() -> str | None:
    """The current repository commit, recorded in the artifact so the run is reproducible."""

    pinned = os.environ.get("SHAURYA_CODE_COMMIT")
    if pinned:
        if len(pinned) != 40 or any(character not in "0123456789abcdef" for character in pinned):
            raise ValueError("SHAURYA_CODE_COMMIT must be a lowercase 40-character Git SHA")
        return pinned
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def build_tape_input(tape: Path, *, tape_index: int, horizons: tuple[int, ...]) -> TapeInput:
    """Replay one permitted tape into ordinary-activity observations."""

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
    observations, failures = build_observations(
        depth200_states=depth200,
        depth20_states=depth20,
        tape_index=tape_index,
        run_id=run_id,
        horizons_seconds=horizons,
    )
    observed_seconds = (
        (depth200[-1].receive_ts_ns - depth200[0].receive_ts_ns) / NANOSECONDS_PER_SECOND
        if len(depth200) > 1
        else 0.0
    )
    return TapeInput(
        tape_index=tape_index,
        run_id=run_id,
        instrument_id=instrument_id,
        tape_sha256=computed,
        observations=tuple(observations),
        depth200_publications=len(depth200),
        depth20_publications=len(depth20),
        observed_seconds=observed_seconds,
        failures=failures,
    )


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
        "--nested-rows-output",
        type=Path,
        default=None,
        help="Optional JSONL path for one flattened row per nested-ladder rung and step.",
    )
    parser.add_argument(
        "--association-rows-output",
        type=Path,
        default=None,
        help="Optional JSONL path for the complete feature-by-horizon association tables.",
    )
    parser.add_argument(
        "--replicates",
        type=int,
        default=BLOCK_BOOTSTRAP_REPLICATES,
        help="Stationary block bootstrap replicates.",
    )
    parser.add_argument("--seed", type=int, default=BOOTSTRAP_SEED, help="Bootstrap seed.")
    parser.add_argument(
        "--skip-yardstick",
        action="store_true",
        help="Skip the flexible yardstick model (the slowest stage).",
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
    tapes = [
        build_tape_input(tape, tape_index=tape_index, horizons=tuple(HORIZONS_SECONDS))
        for tape_index, tape in enumerate(args.tape)
    ]
    return build_normal_activity_artifact(
        tapes,
        code_commit=code_commit(),
        replicates=args.replicates,
        seed=args.seed,
        include_yardstick=not args.skip_yardstick,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        artifact = run(args)
    except (ConfirmatoryUseRefused, TapeNotPermitted) as error:
        print(json.dumps({"status": "refused", "reason": str(error)}))
        return 2
    _write(args.output, json.dumps(artifact, indent=2, sort_keys=True, default=str) + "\n")
    if args.nested_rows_output is not None:
        _write(
            args.nested_rows_output,
            "".join(
                json.dumps(row, sort_keys=True, default=str) + "\n"
                for row in nested_rows(artifact)
            ),
        )
    if args.association_rows_output is not None:
        _write(
            args.association_rows_output,
            "".join(
                json.dumps(row, sort_keys=True, default=str) + "\n"
                for row in association_rows(artifact)
            ),
        )
    print(
        json.dumps(
            {
                "status": "ok",
                "exploratory_scan_id": artifact["protocol"]["exploratory_scan_id"],
                "confirmatory_eligible": artifact["protocol"]["confirmatory_eligible"],
                "output": str(args.output),
                "observations": artifact["totals"]["observations"],
                "features_per_observation": artifact["totals"]["features_per_observation"],
                "train_n": artifact["split"]["train_n"],
                "test_n": artifact["split"]["test_n"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
