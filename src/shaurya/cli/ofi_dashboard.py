"""ANL-06: serve the dynamic OFI dashboard from a JSONL tape, without a Dhan socket.

``replay`` consumes a pinned completed tape deterministically in capture time.  ``follow`` polls
the bytes of a growing tape written by another process and retains a torn trailing line until its
newline arrives.  Both modes use the same complete-line reader and walk-forward engine.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from shaurya.analytics.ofi_dashboard import (
    OfiDashboardEngine,
    RefitArtifactSink,
    WalkForwardConfig,
)
from shaurya.analytics.ofi_dashboard_server import OfiDashboardState, serve_in_background
from shaurya.contracts.data import DatasetHandle, DatasetStatus
from shaurya.contracts.timing import IST
from shaurya.data.access import DataAccess, DataCatalog
from shaurya.data.storage import resolve_data_catalog
from shaurya.data.tape import CompleteLineJsonlTail

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8776


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("replay", "follow"), required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--dataset-id", help="CON-10 DAT dataset ID from the shared catalogue")
    source.add_argument(
        "--tape",
        type=Path,
        help="Legacy evidence path; DAT adopts, indexes and returns a handle before ANL ingests",
    )
    parser.add_argument(
        "--data-catalog",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--trading-date",
        type=date.fromisoformat,
        default=datetime.now(IST).date(),
        help="IST catalogue partition date (required for an archived replay from another day)",
    )
    parser.add_argument(
        "--allow-nonarchive-catalog",
        action="store_true",
        help="Permit a controlled isolated DAT catalogue outside the verified NSE archive",
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--refit-cadence-seconds", type=float, default=60.0)
    parser.add_argument("--test-block-seconds", type=float, default=120.0)
    parser.add_argument("--minimum-training-anchors", type=int, default=600)
    parser.add_argument("--minimum-test-anchors", type=int, default=20)
    parser.add_argument("--bootstrap-replicates", type=int, default=399)
    parser.add_argument("--seed", type=int, default=20260820)
    parser.add_argument("--poll-seconds", type=float, default=0.2)
    parser.add_argument("--replay-speed", type=float, default=0.0)
    parser.add_argument(
        "--serve-seconds",
        type=float,
        default=0.0,
        help="replay: retain final screen this long; follow: stop after this wall-clock duration; "
        "zero means immediate exit for replay and until interrupted for follow",
    )
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _config(args: argparse.Namespace) -> WalkForwardConfig:
    return WalkForwardConfig(
        test_block_seconds=args.test_block_seconds,
        refit_cadence_seconds=args.refit_cadence_seconds,
        minimum_training_anchors=args.minimum_training_anchors,
        minimum_test_anchors=args.minimum_test_anchors,
        bootstrap_replicates=args.bootstrap_replicates,
        seed=args.seed,
    )


def _engine(
    args: argparse.Namespace,
    tail: CompleteLineJsonlTail,
    handle: DatasetHandle,
) -> tuple[OfiDashboardEngine, RefitArtifactSink]:
    tape = Path(handle.tape_path)
    identity = (
        f"dat:{handle.dataset_id}#sha256={handle.tape_sha256 or _sha256(tape)}"
        if args.mode == "replay"
        else f"dat:{handle.dataset_id}#growing-read-only"
    )
    sink = RefitArtifactSink(args.artifact_dir)
    engine = OfiDashboardEngine(
        run_id=f"anl06-{handle.dataset_id}",
        drive_mode=args.mode,
        tape_identity=identity,
        config=_config(args),
        artifact_sink=sink,
    )
    del tail  # construction is intentionally independent of transport state
    return engine, sink


def _ingest_batch(
    engine: OfiDashboardEngine,
    rows: tuple[dict[str, Any], ...],
    *,
    replay_speed: float,
    first_stamp: list[int | None],
    started: float,
    refit_each_due_row: bool,
) -> None:
    for row in rows:
        raw = row.get("receive_ts")
        if replay_speed > 0 and isinstance(raw, str):
            from shaurya.data.depth_thinning_analysis import parse_receive_ts_ns

            stamp = parse_receive_ts_ns(raw)
            if first_stamp[0] is None:
                first_stamp[0] = stamp
            origin = first_stamp[0]
            if origin is None:  # defensive: assigned immediately above
                raise AssertionError("replay origin was not initialised")
            target = (stamp - origin) / 1_000_000_000 / replay_speed
            delay = target - (time.monotonic() - started)
            if delay > 0:
                time.sleep(delay)
        engine.ingest_dict(row)
        if refit_each_due_row and engine.due_for_refit():
            engine.refit()
    if not refit_each_due_row and rows and engine.due_for_refit():
        # Follow mode ingests the whole file-tail batch before fitting.  If fitting runs past a
        # cadence, newly appended rows produce one latest fit rather than a queue of stale fits.
        engine.refit()


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.poll_seconds <= 0 or args.replay_speed < 0 or args.serve_seconds < 0:
        raise ValueError("poll must be positive; replay speed and serve duration non-negative")
    catalog_path = resolve_data_catalog(
        args.data_catalog,
        trading_date=args.trading_date,
        allow_nonarchive=args.allow_nonarchive_catalog,
    )
    access = DataAccess(DataCatalog(catalog_path))
    handle = (
        access.handle(args.dataset_id)
        if args.dataset_id is not None
        else access.adopt_legacy_tape(
            args.tape,
            consumer="ANL-06",
            purpose="dynamic OFI dashboard",
        )
    )
    if args.mode == "replay" and handle.status is DatasetStatus.ACTIVE:
        raise ValueError("replay requires a completed DAT dataset; use follow for active data")
    tail = access.follow(handle)
    tape = Path(handle.tape_path)
    engine, _ = _engine(args, tail, handle)
    state = OfiDashboardState(engine, tail)
    server, _ = serve_in_background(state, host=args.host, port=args.port)
    print(f"ANL-06 read-only dashboard serving at http://{args.host}:{args.port}/", flush=True)
    started = time.monotonic()
    first_stamp: list[int | None] = [None]
    error: BaseException | None = None
    try:
        if args.mode == "replay":
            while tail.offset < tape.stat().st_size:
                batch = tail.poll()
                _ingest_batch(
                    engine,
                    batch.rows,
                    replay_speed=args.replay_speed,
                    first_stamp=first_stamp,
                    started=started,
                    refit_each_due_row=True,
                )
            if tail.trailing_partial_bytes:
                raise ValueError("completed replay tape ends in a torn JSONL line")
            if engine.due_for_refit():
                engine.refit()
            if args.serve_seconds:
                time.sleep(args.serve_seconds)
        else:
            while args.serve_seconds == 0 or time.monotonic() - started < args.serve_seconds:
                batch = tail.poll()
                _ingest_batch(
                    engine,
                    batch.rows,
                    replay_speed=0.0,
                    first_stamp=first_stamp,
                    started=started,
                    refit_each_due_row=False,
                )
                time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        pass
    except BaseException as exc:  # noqa: BLE001 - returned in the run summary
        error = exc
    finally:
        server.shutdown()
    summary = engine.close_artifacts() or {}
    summary.update(
        {
            "rows_parsed": tail.rows_parsed,
            "malformed_lines": tail.malformed_lines,
            "torn_lines": tail.torn_lines,
            "trailing_partial_bytes": tail.trailing_partial_bytes,
            "error": None if error is None else type(error).__name__,
        }
    )
    if error is not None:
        raise error
    return summary


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    summary = run(args)
    json.dump(summary, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
