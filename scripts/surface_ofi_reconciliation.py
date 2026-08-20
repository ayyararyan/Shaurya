#!/usr/bin/env python3
"""Reconcile displayed eSSVI with the exact prior DAT-20 OFI horse-race sample."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ofi_horserace import (
    _ablation_csv,
    _gate_csv,
    _intensity_csv,
    _jsonl,
    _ranking_csv,
    _support_csv,
    build_tape_input,
)
from shaurya.signals.ofi_horserace import build_horserace_artifact
from shaurya.signals.surface_ofi_reconciliation import (
    RECONCILIATION_ID,
    build_reconciliation_artifact,
    join_record_to_dict,
    surface_observation_from_dict,
)

HORSE_EXECUTION_COMMIT = "c18a4bd959ea6e882625a37c57d75211969f06dc"
EXPECTED_HORSE_HASHES = {
    "summary": "a91bd7e1535a160cb0cc0a8d714af47cc37d2c088c6dc43e3d037153fd8091b1",
    "cells": "dc531ff38e18dad61871bd8f3423df4136041924bdbe7742661d4ea61eebe75f",
    "past": "969c2530e8cccc1e6808ec5d1cf914d2a14c87365a4545d46217f11fc41f3c25",
    "ranking": "720ccd738fa4f88c3002e2ad8fdde94968f35b1ca17a4fc7d4197382ff5c8bb8",
    "ablation": "1c3681c76546f98920dd9d889f09f1ac5268d0220f41a71fbaf58ac8961ae4bb",
    "intensity": "5134669ac108a21cc954c6e010f42ed623c49548e20984450f097333b08c82c9",
    "support": "c9dc12b94030c0404b29d04195da5d24d67e4754d1e2e341e54e5136dfcb053d",
    "gate": "efe6359b6881f2b78281f118b28f8ecfc217e10e39fe85accab9ef18389c2a07",
}


def code_commit() -> str | None:
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


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _compact_jsonl(rows: Sequence[Mapping[str, Any]]) -> str:
    return "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
        for row in rows
    )


def _csv(rows: Sequence[Mapping[str, Any]]) -> str:
    fields = sorted({key for row in rows for key in row})
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: (
                    json.dumps(value, sort_keys=True, separators=(",", ":"))
                    if isinstance(value, (dict, list, tuple))
                    else value
                )
                for key, value in row.items()
            }
        )
    return output.getvalue()


def _write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial.{os.getpid()}")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _reproduction_payloads(artifact: Mapping[str, Any]) -> dict[str, str]:
    return {
        "summary": json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        "cells": _jsonl(list(artifact["future_cells"])),
        "past": _jsonl(list(artifact["past_mirror_cells"])),
        "ranking": _ranking_csv(list(artifact["rankings"])),
        "ablation": _ablation_csv(list(artifact["combined_ablations"])),
        "intensity": _intensity_csv(list(artifact["feature_intensity"])),
        "support": _support_csv(list(artifact["support_table"])),
        "gate": _gate_csv(dict(artifact["gate_30_seconds"])),
    }


def run(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    if len(args.horse_tape) != 2:
        raise ValueError("the correction consumes the exact two DAT-20 horse-race tapes")
    if args.replicates < 2:
        raise ValueError("at least two bootstrap replicates are required")
    surface_rows = [
        surface_observation_from_dict(json.loads(line))
        for line in args.surface_observations.open(encoding="utf-8")
    ]
    tape_inputs = [
        build_tape_input(path, tape_index=index)
        for index, path in enumerate(args.horse_tape)
    ]
    reproduced = build_horserace_artifact(
        tape_inputs,
        code_commit=HORSE_EXECUTION_COMMIT,
        replicates=args.replicates,
        seed=args.seed,
    )
    payloads = _reproduction_payloads(reproduced)
    observed_hashes = {
        key: sha256_bytes(payload.encode("utf-8")) for key, payload in payloads.items()
    }
    mismatches = {
        key: {"expected": EXPECTED_HORSE_HASHES[key], "observed": observed_hashes[key]}
        for key in EXPECTED_HORSE_HASHES
        if observed_hashes[key] != EXPECTED_HORSE_HASHES[key]
    }
    if mismatches:
        raise AssertionError(f"exact horse-race reproduction failed: {mismatches}")
    horse_observations = [item for tape in tape_inputs for item in tape.observations]
    source = {
        "surface_observations": str(args.surface_observations),
        "surface_observations_sha256": sha256_file(args.surface_observations),
        "horse_tapes": [
            {
                "path": str(path),
                "sha256": tape.tape_sha256,
                "run_id": tape.run_id,
                "instrument_id": tape.instrument_id,
            }
            for path, tape in zip(args.horse_tape, tape_inputs, strict=True)
        ],
    }
    artifact, records = build_reconciliation_artifact(
        horse_observations,
        surface_rows,
        source_metadata=source,
        reproduction_hashes={
            "passed": True,
            "execution_commit_reproduced": HORSE_EXECUTION_COMMIT,
            "artifacts_matched": len(observed_hashes),
            "sha256": observed_hashes,
        },
        code_commit=code_commit(),
        replicates=args.replicates,
        seed=args.seed,
    )
    return artifact, [join_record_to_dict(item) for item in records], payloads


def write_artifacts(
    output_dir: Path,
    artifact: Mapping[str, Any],
    join_rows: Sequence[Mapping[str, Any]],
    reproduction_payloads: Mapping[str, str],
    *,
    exact_cli: str,
) -> dict[str, Any]:
    paths: dict[str, Path] = {
        "summary": output_dir / "surface_ofi_reconciliation_summary.json",
        "join": output_dir / "surface_ofi_reconciliation_join.jsonl",
        "model_scores": output_dir / "surface_ofi_reconciliation_model_scores.csv",
        "paired_inference": output_dir / "surface_ofi_reconciliation_paired_inference.csv",
    }
    _write(paths["summary"], _json(artifact))
    _write(paths["join"], _compact_jsonl(join_rows))
    _write(paths["model_scores"], _csv(list(artifact["model_scores"])))
    _write(paths["paired_inference"], _csv(list(artifact["paired_inference"])))
    for key, payload in reproduction_payloads.items():
        suffix = "json" if key == "summary" else "jsonl" if key in {"cells", "past"} else "csv"
        path = output_dir / f"reproduced_ofi_horserace_{key}.{suffix}"
        _write(path, payload)
        paths[f"reproduced_{key}"] = path
    manifest = {
        "reconciliation_id": RECONCILIATION_ID,
        "exact_cli": exact_cli,
        "code_commit": artifact.get("code_commit"),
        "files": {
            key: {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for key, path in sorted(paths.items())
        },
    }
    _write(output_dir / "artifact_manifest.json", _json(manifest))
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface-observations", required=True, type=Path)
    parser.add_argument("--horse-tape", action="append", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--replicates", type=int, default=400)
    parser.add_argument("--seed", type=int, default=20260819)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    artifact, join_rows, reproduction_payloads = run(args)
    exact_cli = (
        "PYTHONPATH=src python -m scripts.surface_ofi_reconciliation "
        f"--surface-observations {args.surface_observations} "
        + " ".join(f"--horse-tape {path}" for path in args.horse_tape)
        + f" --output-dir {args.output_dir} --replicates {args.replicates} --seed {args.seed}"
    )
    manifest = write_artifacts(
        args.output_dir,
        artifact,
        join_rows,
        reproduction_payloads,
        exact_cli=exact_cli,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "reconciliation_id": RECONCILIATION_ID,
                "joined_observations": artifact["sample"]["joined_observations"],
                "test_n": artifact["sample"]["test_n"],
                "M3bS_minus_M3b": artifact["headline"]["M3bS_minus_M3b"],
                "manifest_file_count": len(manifest["files"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
