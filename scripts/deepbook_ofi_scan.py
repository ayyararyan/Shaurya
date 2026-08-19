#!/usr/bin/env python3
"""Run exploratory price-keyed OFI scan `X-OFI-DAT20-03`."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from scripts.sig21_construction_replay import (
    capture_metrics_for,
    iter_tape_rows,
    manifest_sha256_for,
    sha256_file,
    verify_instrument,
)
from shaurya.data.depth_thinning_analysis import DEPTH20, DEPTH200, build_states
from shaurya.signals.deep_book_normal_activity import (
    BLOCK_BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    assert_permitted_tape,
)
from shaurya.signals.deep_book_ofi import (
    OFITapeInput,
    build_ofi_artifact,
    build_ofi_observations,
)
from shaurya.signals.deep_book_response import NANOSECONDS_PER_SECOND


def code_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, check=True, text=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def build_tape_input(tape: Path, *, tape_index: int) -> OFITapeInput:
    metrics = capture_metrics_for(tape)
    run_id, instrument_id, _, _ = verify_instrument(metrics, tape)
    computed = sha256_file(tape)
    recorded = manifest_sha256_for(tape)
    if recorded is not None and recorded != computed:
        raise ValueError(f"{tape} SHA-256 {computed} does not match manifest {recorded}")
    assert_permitted_tape(run_id=run_id, tape_sha256=computed)
    rows = list(iter_tape_rows(tape))
    depth200 = build_states(rows, DEPTH200)
    depth20 = build_states(rows, DEPTH20)
    observations, failures = build_ofi_observations(
        depth200_states=depth200,
        depth20_states=depth20,
        tape_index=tape_index,
        run_id=run_id,
    )
    observed_seconds = (
        (depth200[-1].receive_ts_ns - depth200[0].receive_ts_ns) / NANOSECONDS_PER_SECOND
        if len(depth200) > 1
        else 0.0
    )
    return OFITapeInput(
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


def _write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tape", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--grid-output", required=True, type=Path)
    parser.add_argument("--nested-output", required=True, type=Path)
    parser.add_argument("--replicates", type=int, default=BLOCK_BOOTSTRAP_REPLICATES)
    parser.add_argument("--seed", type=int, default=BOOTSTRAP_SEED)
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    tapes = [build_tape_input(tape, tape_index=index) for index, tape in enumerate(args.tape)]
    return build_ofi_artifact(
        tapes,
        code_commit=code_commit(),
        replicates=args.replicates,
        seed=args.seed,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    artifact = run(args)
    _write(args.output, json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    _write(
        args.grid_output,
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in artifact["grid"]),
    )
    _write(
        args.nested_output,
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in artifact["nested_depth"]),
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "output": str(args.output),
                "grid_rows": len(artifact["grid"]),
                "observations": artifact["totals"]["observations"],
                "train_n": artifact["totals"]["train_n"],
                "test_n": artifact["totals"]["test_n"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
