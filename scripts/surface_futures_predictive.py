#!/usr/bin/env python3
"""Run frozen exploratory scan `X-SURFACE-FUT5-20260819-06` on the pinned ANL-03 tape."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from shaurya.analytics.surface_feed import (
    SurfaceEngine,
    default_log_moneyness_grid,
)
from shaurya.contracts.tape import TapeRow
from shaurya.contracts.timing import IST
from shaurya.data.depth_thinning_analysis import FULL, BookState, parse_receive_ts_ns
from shaurya.signals.surface_futures_predictive import (
    EXPIRIES,
    FIT_INTERVAL_SECONDS,
    FUTURES_INSTRUMENT_ID,
    SCAN_ID,
    FrameDraft,
    build_predictive_observations,
    build_scan_artifact,
    chronological_split,
    frame_draft,
    observation_to_dict,
)

PINNED_TAPE = Path(
    "/Users/maheit/Documents/Shaurya/data/live-captures/anl03-live/"
    "sha-20260819T063412.584779Z-0a555c5b/"
    "tape_sha-20260819T063412.584779Z-0a555c5b.jsonl"
)
PINNED_SHA256 = "f85b4bdb4c6cce15664849dbf7405d89d35b89a258a2834d94acb0004108a28f"
PINNED_BYTES = 9_149_464_566
PINNED_ROWS = 5_496_592


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


def _levels(raw: object) -> tuple[tuple[float, int, int], ...]:
    if not isinstance(raw, list):
        return ()
    result: list[tuple[float, int, int]] = []
    for value in raw:
        if not isinstance(value, dict):
            continue
        price = value.get("price")
        quantity = value.get("quantity")
        orders = value.get("orders")
        if price is None or quantity is None or orders is None:
            continue
        result.append((round(float(price), 2), int(quantity), int(orders)))
    return tuple(result)


def future_state(raw: Mapping[str, Any]) -> BookState | None:
    if raw.get("event_type") != FULL or raw.get("instrument_id") != FUTURES_INSTRUMENT_ID:
        return None
    timestamp = raw.get("receive_ts")
    if not isinstance(timestamp, str):
        return None
    return BookState(
        channel=FULL,
        receive_ts_ns=parse_receive_ts_ns(timestamp),
        receive_sequence=int(raw.get("receive_sequence") or 0),
        connection_epoch=int(raw.get("connection_epoch") or 0),
        bids=_levels(raw.get("bids")),
        asks=_levels(raw.get("asks")),
        rows_in_burst=1,
        quality_flags=tuple(sorted(str(value) for value in raw.get("quality_flags") or ())),
    )


def replay_tape(
    tape: Path,
) -> tuple[list[FrameDraft], list[BookState], dict[str, Any], dict[str, Any]]:
    """One streaming pass: hash, replay displayed surfaces and retain only front-future states."""

    resolved = tape.resolve()
    if resolved != PINNED_TAPE.resolve():
        raise ValueError(f"scan is pinned to {PINNED_TAPE}; refusing {resolved}")
    if tape.stat().st_size != PINNED_BYTES:
        raise ValueError(
            f"pinned tape size changed: expected {PINNED_BYTES}, found {tape.stat().st_size}"
        )
    engine = SurfaceEngine(
        run_id="sha-20260819T063412.584779Z-0a555c5b",
        surface_id=SCAN_ID,
        expiries=EXPIRIES,
        log_moneyness_grid=default_log_moneyness_grid(),
        fit_interval_seconds=FIT_INTERVAL_SECONDS,
        wall_clock=False,
        history_limit=2,
    )
    digest = hashlib.sha256()
    row_count = 0
    first_receive_ts: str | None = None
    last_receive_ts: str | None = None
    drafts: list[FrameDraft] = []
    futures: list[BookState] = []
    attempted_fits = 0
    successful_fits = 0
    failed_fits = 0
    successful_without_previous = 0
    surface_feature_failures = 0
    previous_levels: dict[str, float] | None = None
    previous_ts_ns: int | None = None
    with tape.open("rb") as handle:
        for binary_line in handle:
            digest.update(binary_line)
            row_count += 1
            loaded = json.loads(binary_line)
            if not isinstance(loaded, dict):
                raise ValueError(f"tape row {row_count} is not an object")
            raw: dict[str, Any] = loaded
            receive_ts = raw.get("receive_ts")
            if isinstance(receive_ts, str):
                first_receive_ts = first_receive_ts or receive_ts
                last_receive_ts = receive_ts
            state = future_state(raw)
            if state is not None:
                futures.append(state)
            row = TapeRow.from_dict(raw)
            engine.ingest(row)
            stamp = row.receive_ts.astimezone(IST)
            if not engine.due_for_fit(stamp):
                continue
            attempted_fits += 1
            snapshot = engine.fit(stamp)
            if not snapshot.fit_ok:
                failed_fits += 1
                continue
            successful_fits += 1
            draft, current_levels = frame_draft(snapshot, previous_levels, previous_ts_ns)
            timestamp_ns = int(round(snapshot.fit_timestamp.timestamp() * 1_000_000_000))
            if current_levels is None:
                surface_feature_failures += 1
                continue
            if draft is None:
                successful_without_previous += 1
            else:
                drafts.append(draft)
            previous_levels = current_levels
            previous_ts_ns = timestamp_ns
    computed_sha = digest.hexdigest()
    if computed_sha != PINNED_SHA256:
        raise ValueError(
            f"pinned tape SHA-256 changed: expected {PINNED_SHA256}, found {computed_sha}"
        )
    if row_count != PINNED_ROWS:
        raise ValueError(
            f"pinned tape row count changed: expected {PINNED_ROWS}, found {row_count}"
        )
    if not futures or any(state.connection_epoch <= 0 for state in futures):
        raise ValueError("pinned tape has no valid front-future Full states")
    source = {
        "tape": str(tape),
        "sha256": computed_sha,
        "bytes": tape.stat().st_size,
        "rows": row_count,
        "first_receive_ts": first_receive_ts,
        "last_receive_ts": last_receive_ts,
        "instrument_id": FUTURES_INSTRUMENT_ID,
        "book_channel": "Quote/Full embedded five-level book; not depth20/depth200",
    }
    replay = {
        "attempted_fits": attempted_fits,
        "successful_fits": successful_fits,
        "failed_fits": failed_fits,
        "successful_without_previous_frame": successful_without_previous,
        "surface_feature_failures": surface_feature_failures,
        "surface_drafts": len(drafts),
        "front_future_full_states": len(futures),
        "fit_engine": (
            "SurfaceEngine unchanged: three pinned expiries, 5s cadence, existing forward "
            "selection/eSSVI/no-arbitrage/SUR-07 smoothing"
        ),
        "live_fit_duration_identification": (
            "unidentified from tape; fixed missing quality column; replay CPU duration excluded"
        ),
    }
    return drafts, futures, source, replay


def _json(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _jsonl(rows: Iterable[object]) -> str:
    return "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
        for row in rows
    )


def _csv(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return ""
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_artifacts(
    output_dir: Path,
    artifact: Mapping[str, Any],
    observations: Sequence[object],
    *,
    exact_cli: str,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "summary": output_dir / "surface_futures_predictive_summary.json",
        "observations": output_dir / "surface_futures_predictive_observations.jsonl",
        "model_scores": output_dir / "surface_futures_predictive_model_scores.csv",
        "correlations": output_dir / "surface_futures_predictive_correlations.csv",
        "coefficients": output_dir / "surface_futures_predictive_coefficients.csv",
        "paired_inference": output_dir / "surface_futures_predictive_paired_inference.csv",
        "freshness": output_dir / "surface_futures_predictive_freshness.csv",
        "lag_placebo": output_dir / "surface_futures_predictive_lag_placebo.csv",
        "horse_aligned_scores": (
            output_dir / "surface_futures_predictive_horse_aligned_scores.csv"
        ),
        "horse_aligned_inference": (
            output_dir / "surface_futures_predictive_horse_aligned_inference.csv"
        ),
    }
    _write(paths["summary"], _json(artifact))
    _write(paths["observations"], _jsonl(observations))
    for key in (
        "model_scores",
        "correlations",
        "coefficients",
        "paired_inference",
        "freshness",
        "lag_placebo",
        "horse_aligned_scores",
        "horse_aligned_inference",
    ):
        artifact_key = {
            "horse_aligned_scores": "horse_aligned_full_session_scores",
            "horse_aligned_inference": "horse_aligned_full_session_inference",
        }.get(key, key)
        rows = artifact[artifact_key]
        if not isinstance(rows, list):
            raise ValueError(f"artifact section {key} is not a list")
        _write(paths[key], _csv(rows))
    manifest = {
        "scan_id": SCAN_ID,
        "exact_cli": exact_cli,
        "source_tape_sha256": PINNED_SHA256,
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
    parser.add_argument("--tape", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--replicates", type=int, default=400)
    parser.add_argument("--seed", type=int, default=20260819)
    return parser


def run(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if args.replicates < 2:
        raise ValueError("at least two stationary-bootstrap replicates are required")
    drafts, futures, source, replay = replay_tape(args.tape)
    observations, join_failures = build_predictive_observations(drafts, futures)
    split = chronological_split(observations)
    replay = {**replay, "join_failures": join_failures}
    artifact = build_scan_artifact(
        observations,
        split,
        source_metadata=source,
        replay_metadata=replay,
        replicates=args.replicates,
        seed=args.seed,
        code_commit=code_commit(),
    )
    return artifact, [observation_to_dict(item) for item in observations]


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    artifact, observations = run(args)
    exact_cli = (
        "PYTHONPATH=src python -m scripts.surface_futures_predictive "
        f"--tape {args.tape} --output-dir {args.output_dir} "
        f"--replicates {args.replicates} --seed {args.seed}"
    )
    manifest = write_artifacts(
        args.output_dir,
        artifact,
        observations,
        exact_cli=exact_cli,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "scan_id": SCAN_ID,
                "observations": artifact["sample"]["common_observations"],
                "train_n": artifact["sample"]["train_n"],
                "test_n": artifact["sample"]["test_n"],
                "LOS_minus_LO_oos_r2": artifact["headline"]["LOS_minus_LO_oos_r2"],
                "manifest": str(args.output_dir / "artifact_manifest.json"),
                "manifest_file_count": len(manifest["files"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
