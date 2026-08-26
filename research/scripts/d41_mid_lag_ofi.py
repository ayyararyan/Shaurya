#!/usr/bin/env python3
"""Run D41's frozen displayed-mid-lag versus CCZ OFI comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ofi_horserace import build_tape_input
from shaurya.signals.mid_lag_ofi import (
    CCZ_LEVELS,
    HORIZONS_SECONDS,
    REGISTRATION_COMMIT,
    build_mid_lag_ofi_artifact,
    compact_result,
)

EXPECTED_TAPE_SHA256 = "93456eda4de33cc22fc1d9d3dc8fb5ca7a7bb8eab7108e3c0ef8859a97759a43"


def _git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    partial.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tape", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--summary-output", required=True, type=Path)
    args = parser.parse_args()

    if _sha256(args.tape) != EXPECTED_TAPE_SHA256:
        raise RuntimeError("D41 tape hash does not match the frozen immutable input")
    commit = _git_commit()
    if not commit.startswith(REGISTRATION_COMMIT):
        registration_check = subprocess.run(
            ["git", "merge-base", "--is-ancestor", REGISTRATION_COMMIT, commit],
            cwd=Path(__file__).resolve().parents[1],
            check=False,
        )
        if registration_check.returncode != 0:
            raise RuntimeError("D41 code does not descend from the pushed registration commit")
    tape = build_tape_input(
        args.tape,
        tape_index=0,
        late_partial_exploratory=True,
        level_counts=(CCZ_LEVELS,),
        response_horizons=HORIZONS_SECONDS,
    )
    artifact = build_mid_lag_ofi_artifact(tape)
    artifact["code_commit"] = commit
    artifact["source_tape"] = str(args.tape)
    artifact["sig19_trial"]["code_commit"] = commit
    _write_atomic(args.output, artifact)
    summary = compact_result(artifact)
    summary["full_artifact_sha256"] = _sha256(args.output)
    _write_atomic(args.summary_output, summary)
    print(
        json.dumps(
            {
                "status": "complete",
                "code_commit": commit,
                "full_artifact": str(args.output),
                "full_artifact_sha256": summary["full_artifact_sha256"],
                "summary": str(args.summary_output),
                "future_cells": len(artifact["future_comparisons"]),
                "lag_horizons": len(artifact["lag_models"]),
                "contemporaneous_cells": len(artifact["contemporaneous_check"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
