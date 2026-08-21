"""Run D50 on a completed DAT tape and write one atomic calibration artifact."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.sig21_construction_replay import (
    capture_metrics_for,
    iter_tape_rows,
    manifest_sha256_for,
    sha256_file,
)
from shaurya.data.depth_thinning_analysis import DEPTH20, DEPTH200, build_states_streaming
from shaurya.signals.nonlinear_ofi_state import HORIZONS_SECONDS, build_calibration_artifact
from shaurya.signals.ofi_horserace import build_horserace_observations


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tape", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial-{os.getpid()}")
    descriptor = os.open(partial, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, path)


def run(tape: Path) -> dict[str, Any]:
    tape = tape.resolve()
    metrics = capture_metrics_for(tape)
    expected = manifest_sha256_for(tape)
    actual = sha256_file(tape)
    if expected is None or expected != actual:
        raise ValueError("completed DAT tape hash does not match its manifest")
    print(json.dumps({"stage": "hash_verified", "sha256": actual}), flush=True)
    depth200 = build_states_streaming(iter_tape_rows(tape), DEPTH200)
    print(json.dumps({"stage": "depth200_loaded", "states": len(depth200)}), flush=True)
    depth20 = build_states_streaming(iter_tape_rows(tape), DEPTH20)
    print(json.dumps({"stage": "depth20_loaded", "states": len(depth20)}), flush=True)
    observations, failures = build_horserace_observations(
        depth200_states=depth200,
        depth20_states=depth20,
        rows=(),
        tape_index=0,
        run_id=str(metrics["run_id"]),
        level_counts=(10,),
        response_horizons=HORIZONS_SECONDS,
    )
    print(
        json.dumps({"stage": "observations_built", "observations": len(observations)}), flush=True
    )
    artifact = build_calibration_artifact(observations)
    artifact["generated_at"] = datetime.now(UTC).isoformat()
    artifact["source"] = {
        "tape": str(tape),
        "tape_sha256": actual,
        "run_id": metrics["run_id"],
        "instrument_id": metrics["instrument_id"],
        "rows": metrics["rows"],
        "opening_gate_missed_seconds": 4.44,
    }
    artifact["observation_failures"] = failures
    return artifact


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    artifact = run(args.tape)
    _write_atomic(args.output, artifact)
    print(json.dumps({"stage": "complete", "output": str(args.output)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
