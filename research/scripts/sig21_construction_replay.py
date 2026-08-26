#!/usr/bin/env python3
"""SIG-21 construction replay: the basic outcome-blind support grid from depth200 tape.

Reproducible entry point that replays the registered `H-SIG21` construction detector over
already-recorded depth200 NIFTY-futures tape and writes the 32-cell construction support grid.

`H-SIG21` §1.2 permanently excludes the post-event price paths of the retained `DAT-20` tapes
from SIG-21 inference. This script therefore computes no response, return, label, midpoint,
markout or outcome, joins no candidate row to a later price state, and refuses -- loudly, before
reading any tape -- any request that names one. No live connection is opened.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from shaurya.signals.deep_book_construction_grid import (
    OUTCOME_JOIN_ALLOWED,
    PROTOCOL_ID,
    SAMPLE_ROLE,
    OutcomeJoinRefused,
    TapeReplay,
    assert_outcome_blind_request,
    build_replay_artifact,
    build_tape_replay,
    grid_rows,
)

REQUIRED_INSTRUMENT_KIND = "future"
SHA_CHUNK_BYTES = 1 << 20


def sha256_file(path: Path) -> str:
    """SHA-256 of an input tape, recorded in the artifact so the source is pinned."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(SHA_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_tape_rows(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if isinstance(row, dict):
                yield row


def manifest_sha256_for(tape: Path) -> str | None:
    """The SHA-256 the collector itself recorded for this tape, if a manifest is present."""

    run_id = tape.stem.removeprefix("tape_")
    manifest = tape.parent / f"manifest_{run_id}.jsonl"
    if not manifest.exists():
        return None
    with manifest.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if (
                isinstance(record, dict)
                and record.get("event_type") == "artifact_closed"
                and record.get("artifact") == tape.name
            ):
                recorded = record.get("sha256")
                return str(recorded) if recorded else None
    return None


def capture_metrics_for(tape: Path) -> dict[str, Any]:
    """Locate the sibling capture_metrics document written alongside a retained tape."""

    run_id = tape.stem.removeprefix("tape_")
    candidate = tape.parent / f"capture_metrics_{run_id}.json"
    if not candidate.exists():
        raise FileNotFoundError(f"capture metrics not found for {tape}: expected {candidate}")
    with candidate.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"capture metrics for {tape} is not an object")
    return loaded


def verify_instrument(metrics: dict[str, Any], tape: Path) -> tuple[str, str, str, str]:
    """Confirm the tape is the NIFTY front-month future before any replay work is done."""

    instrument_id = str(metrics.get("instrument_id") or "")
    run_id = str(metrics.get("run_id") or "")
    security_id = str(metrics.get("dhan_security_id") or "")
    symbol = str(metrics.get("trading_symbol") or "")
    parts = instrument_id.split(":")
    if len(parts) < 4 or parts[3] != REQUIRED_INSTRUMENT_KIND:
        raise ValueError(
            f"{tape} is instrument {instrument_id!r}, which is not a future. H-SIG21 §2 registers "
            "the NIFTY front-month future; refusing to replay a different instrument class."
        )
    if "NIFTY" not in instrument_id.upper():
        raise ValueError(f"{tape} is instrument {instrument_id!r}, which is not a NIFTY contract.")
    missing = [
        name
        for name, value in (
            ("run_id", run_id),
            ("dhan_security_id", security_id),
            ("trading_symbol", symbol),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"{tape} capture metrics is missing {', '.join(missing)}")
    return run_id, instrument_id, security_id, symbol


def replay_tape(tape: Path) -> TapeReplay:
    metrics = capture_metrics_for(tape)
    run_id, instrument_id, security_id, symbol = verify_instrument(metrics, tape)
    computed = sha256_file(tape)
    recorded = manifest_sha256_for(tape)
    if recorded is not None and recorded != computed:
        raise ValueError(
            f"{tape} SHA-256 {computed} does not match the manifest value {recorded}; the "
            "retained tape has changed since capture and must not be replayed."
        )
    return build_tape_replay(
        iter_tape_rows(tape),
        run_id=run_id,
        tape_sha256=computed,
        instrument_id=instrument_id,
        dhan_security_id=security_id,
        trading_symbol=symbol,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tape",
        required=True,
        action="append",
        type=Path,
        help="Retained depth200 tape JSONL (repeatable).",
    )
    parser.add_argument("--output", required=True, type=Path, help="Artifact JSON path.")
    parser.add_argument(
        "--grid-rows-output",
        type=Path,
        default=None,
        help="Optional JSONL path for one flattened row per construction cell.",
    )
    parser.add_argument(
        "--section",
        action="append",
        default=None,
        help=(
            "Optional named section request. Any name referring to a response, return, label, "
            f"midpoint, markout or outcome is refused under {PROTOCOL_ID} §1.2."
        ),
    )
    return parser


def _write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)


def run(args: argparse.Namespace) -> dict[str, Any]:
    requested = list(args.section or ())
    # Refused before any tape is opened, so a forbidden request cannot even read the input.
    assert_outcome_blind_request(requested)
    replays = [replay_tape(tape) for tape in args.tape]
    return build_replay_artifact(replays, requested_sections=requested)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        artifact = run(args)
    except OutcomeJoinRefused as error:
        print(json.dumps({"status": "refused", "reason": str(error)}))
        return 2
    _write(args.output, json.dumps(artifact, indent=2, sort_keys=True, default=str) + "\n")
    if args.grid_rows_output is not None:
        rows = grid_rows(artifact)
        payload = "".join(
            json.dumps(row, sort_keys=True, default=str) + "\n" for row in rows
        )
        _write(args.grid_rows_output, payload)
    print(
        json.dumps(
            {
                "status": "ok",
                "protocol_id": PROTOCOL_ID,
                "sample_role": SAMPLE_ROLE,
                "outcome_join_allowed": OUTCOME_JOIN_ALLOWED,
                "output": str(args.output),
                "candidates": artifact["totals"]["candidates"],
                "non_overlapping_episodes": artifact["totals"]["non_overlapping_episodes"],
                "construction_cells_populated": artifact["family_decomposition"][
                    "construction_cells_populated"
                ],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
