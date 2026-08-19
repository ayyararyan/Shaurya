#!/usr/bin/env python3
"""Run the exploratory Cont-Kukanov-Stoikov level-one OFI scan `X-CKS-L1-OFI-DAT20-04`."""

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
from shaurya.data.depth_thinning_analysis import (
    DEPTH20,
    DEPTH200,
    build_states,
    build_states_streaming,
)
from shaurya.data.ofi_replication import (
    PROTOCOL_ID as REPLICATION_PROTOCOL_ID,
)
from shaurya.data.ofi_replication import (
    REGISTRATION_COMMIT as REPLICATION_REGISTRATION_COMMIT,
)
from shaurya.data.ofi_replication import (
    filtered_session_rows,
    inspect_replication_capture,
    iter_session_rows,
    require_accepted_receipt,
)
from shaurya.signals.cks_l1_ofi import (
    CksL1TapeInput,
    build_cks_l1_artifact,
    build_cks_l1_observations,
    build_trade_totals,
)
from shaurya.signals.deep_book_normal_activity import (
    BLOCK_BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    assert_permitted_tape,
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


def build_tape_input(
    tape: Path, *, tape_index: int, full_session_replication: bool = False
) -> CksL1TapeInput:
    metrics = capture_metrics_for(tape)
    run_id, instrument_id, _, _ = verify_instrument(metrics, tape)
    computed = sha256_file(tape)
    recorded = manifest_sha256_for(tape)
    if recorded is not None and recorded != computed:
        raise ValueError(f"{tape} SHA-256 {computed} does not match manifest {recorded}")
    if full_session_replication:
        receipt = inspect_replication_capture(
            tape,
            metrics,
            tape_sha256=computed,
            manifest_sha256=recorded,
        )
        require_accepted_receipt(receipt)
        depth200 = build_states_streaming(iter_session_rows(tape), DEPTH200)
        depth20 = build_states_streaming(iter_session_rows(tape), DEPTH20)
        rows = filtered_session_rows(tape, {"full"})
    else:
        assert_permitted_tape(run_id=run_id, tape_sha256=computed)
        rows = list(iter_tape_rows(tape))
        depth200 = build_states(rows, DEPTH200)
        depth20 = build_states(rows, DEPTH20)
    observations, failures, intensities = build_cks_l1_observations(
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
    return CksL1TapeInput(
        tape_index=tape_index,
        run_id=run_id,
        instrument_id=instrument_id,
        tape_sha256=computed,
        observations=tuple(observations),
        depth200_publications=len(depth200),
        depth20_publications=len(depth20),
        observed_seconds=observed_seconds,
        failures=failures,
        intensities=intensities,
        trades=build_trade_totals(rows),
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
    parser.add_argument("--components-output", required=True, type=Path)
    parser.add_argument("--replicates", type=int, default=BLOCK_BOOTSTRAP_REPLICATES)
    parser.add_argument("--seed", type=int, default=BOOTSTRAP_SEED)
    parser.add_argument(
        "--full-session-replication",
        action="store_true",
        help="Validate and clip the registered R-OFI-FULLSESSION-2026-08-20 tape instead of "
        "using the immutable DAT-20 exploratory allowlist.",
    )
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.full_session_replication and len(args.tape) != 1:
        raise ValueError("the registered full-session replication consumes exactly one tape")
    tapes = [
        build_tape_input(
            tape,
            tape_index=index,
            full_session_replication=args.full_session_replication,
        )
        for index, tape in enumerate(args.tape)
    ]
    artifact = build_cks_l1_artifact(
        tapes,
        code_commit=code_commit(),
        replicates=args.replicates,
        seed=args.seed,
    )
    if args.full_session_replication:
        artifact["replication_protocol"] = {
            "protocol_id": REPLICATION_PROTOCOL_ID,
            "registration_commit": REPLICATION_REGISTRATION_COMMIT,
            "source_scan_id": "X-CKS-L1-OFI-DAT20-04",
            "sample_role": "prospective_full_session_replication",
            "confirmatory_eligible": False,
        }
    return artifact


def component_rows(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scope, payload in [
        ("pooled", artifact["component_intensities_pooled"]),
        *[(tape["run_id"], tape["component_intensities"]) for tape in artifact["tapes"]],
    ]:
        for name, values in payload["components"].items():
            rows.append({"scope": scope, "component": name, **values})
    return rows


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    artifact = run(args)
    _write(args.output, json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    _write(
        args.grid_output,
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in artifact["grid"]),
    )
    _write(
        args.components_output,
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in component_rows(artifact)),
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
