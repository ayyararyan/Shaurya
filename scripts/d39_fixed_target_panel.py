#!/usr/bin/env python3
"""Run the frozen D39 panel on a validated read-only late-partial snapshot."""

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

from scripts.ofi_horserace import build_tape_input
from shaurya.data.ofi_live_partial import iter_late_partial_rows
from shaurya.signals.effective_touch import build_trade_prints
from shaurya.signals.fixed_target_panel import (
    CCZ_LEVEL_COUNTS,
    D39_REFERENCE_PRICE_LADDER,
    HORIZONS_SECONDS,
    WINDOWS_SECONDS,
    build_fixed_target_panel,
)


def _git_commit() -> str | None:
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


def _floats(value: str) -> tuple[float, ...]:
    return tuple(float(item) for item in value.split(",") if item)


def _ints(value: str) -> tuple[int, ...]:
    return tuple(int(item) for item in value.split(",") if item)


def _strings(value: str) -> tuple[str, ...]:
    return tuple(item for item in value.split(",") if item)


def _write_atomic(path: Path, payload: MappingLike) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial-{os.getpid()}")
    descriptor = os.open(partial, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, path)


MappingLike = dict[str, Any]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tape", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--progress-output", type=Path)
    parser.add_argument("--references", default=",".join(D39_REFERENCE_PRICE_LADDER), type=_strings)
    parser.add_argument(
        "--levels", default=",".join(str(value) for value in CCZ_LEVEL_COUNTS), type=_ints
    )
    parser.add_argument(
        "--windows", default=",".join(str(value) for value in WINDOWS_SECONDS), type=_floats
    )
    parser.add_argument(
        "--horizons", default=",".join(str(value) for value in HORIZONS_SECONDS), type=_floats
    )
    parser.add_argument("--replicates", type=int, default=399)
    parser.add_argument("--seed", type=int, default=20260820)
    args = parser.parse_args()
    if args.replicates < 0:
        raise ValueError("replicates cannot be negative")
    if not args.references or not args.levels or not args.windows or not args.horizons:
        raise ValueError("every D39 axis must be non-empty")
    unknown = set(args.references) - set(D39_REFERENCE_PRICE_LADDER)
    if unknown:
        raise ValueError(f"unknown D39 references: {sorted(unknown)}")
    if not set(args.levels) <= set(CCZ_LEVEL_COUNTS):
        raise ValueError(f"levels must be drawn from {CCZ_LEVEL_COUNTS}")

    tape = build_tape_input(
        args.tape,
        tape_index=0,
        late_partial_exploratory=True,
        # The shared observation builder retains M=10 as its legacy primary arm.  Include it in
        # construction even when a diagnostic CLI slice requests another M only; the artifact
        # still evaluates exactly ``args.levels``.
        level_counts=tuple(sorted({10, *args.levels})),
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

    try:
        artifact = build_fixed_target_panel(
            tape,
            prints=prints.prints,
            references=args.references,
            levels=args.levels,
            windows=args.windows,
            horizons=args.horizons,
            replicates=args.replicates,
            seed=args.seed,
            progress=progress,
        )
    finally:
        if progress_handle is not None:
            progress_handle.close()
    artifact["code_commit"] = _git_commit()
    artifact["source_tape"] = str(args.tape)
    artifact["trade_print_support"] = {
        "prints": len(prints),
        "schema_packets": prints.schema_packets,
        "excluded_no_increment": prints.excluded_no_increment,
        "excluded_missing_classifier_version": prints.excluded_missing_classifier_version,
        "excluded_wrong_classifier_version": prints.excluded_wrong_classifier_version,
        "excluded_missing_alignment_version": prints.excluded_missing_alignment_version,
        "excluded_wrong_alignment_version": prints.excluded_wrong_alignment_version,
        "excluded_unusable_price": prints.excluded_unusable_price,
        "without_displayed_quote": prints.without_displayed_quote,
    }
    _write_atomic(args.output, artifact)
    print(
        json.dumps(
            {
                "status": "complete",
                "output": str(args.output),
                "cells": len(artifact["cells"]),
                "tape_sha256": artifact["tape"]["sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
