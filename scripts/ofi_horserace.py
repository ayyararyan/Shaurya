#!/usr/bin/env python3
"""Run exploratory predictor horse race `X-OFI-HORSERACE-DAT20-05`."""

from __future__ import annotations

import argparse
import csv
import io
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
from shaurya.signals.deep_book_normal_activity import assert_permitted_tape
from shaurya.signals.deep_book_response import NANOSECONDS_PER_SECOND
from shaurya.signals.ofi_horserace import (
    HorseRaceTapeInput,
    build_horserace_artifact,
    build_horserace_observations,
)


def code_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, check=True, text=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def build_tape_input(tape: Path, *, tape_index: int) -> HorseRaceTapeInput:
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
    observations, failures = build_horserace_observations(
        depth200_states=depth200,
        depth20_states=depth20,
        rows=rows,
        tape_index=tape_index,
        run_id=run_id,
    )
    observed_seconds = (
        (depth200[-1].receive_ts_ns - depth200[0].receive_ts_ns) / NANOSECONDS_PER_SECOND
        if len(depth200) > 1
        else 0.0
    )
    return HorseRaceTapeInput(
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


def _jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def _ranking_csv(rows: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    fields = (
        "h2_seconds",
        "rank",
        "model",
        "h1_seconds",
        "oos_r2",
        "incremental_oos_r2_over_m0",
        "tape_0_increment",
        "tape_1_increment",
    )
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        per_tape = row["per_tape_increment"]
        writer.writerow(
            {
                **{key: row[key] for key in fields[:6]},
                "tape_0_increment": per_tape.get("0"),
                "tape_1_increment": per_tape.get("1"),
            }
        )
    return output.getvalue()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tape", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cells-output", required=True, type=Path)
    parser.add_argument("--past-output", required=True, type=Path)
    parser.add_argument("--ranking-output", required=True, type=Path)
    parser.add_argument("--replicates", type=int, default=400)
    parser.add_argument("--seed", type=int, default=20260819)
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    tapes = [build_tape_input(tape, tape_index=index) for index, tape in enumerate(args.tape)]
    return build_horserace_artifact(
        tapes, code_commit=code_commit(), replicates=args.replicates, seed=args.seed
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    artifact = run(args)
    _write(args.output, json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    _write(args.cells_output, _jsonl(artifact["future_cells"]))
    _write(args.past_output, _jsonl(artifact["past_mirror_cells"]))
    _write(args.ranking_output, _ranking_csv(artifact["rankings"]))
    print(
        json.dumps(
            {
                "status": "ok",
                "output": str(args.output),
                "future_cells": len(artifact["future_cells"]),
                "past_cells": len(artifact["past_mirror_cells"]),
                "observations": artifact["sample"]["observations"],
                "train_n": artifact["sample"]["train_n"],
                "test_n": artifact["sample"]["test_n"],
                "gate_30_seconds": artifact["gate_30_seconds"]["gate_passed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
