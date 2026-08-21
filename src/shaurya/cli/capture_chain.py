"""Read-only Dhan option-chain capture on the Quote/Full channel (`RequestCode` 21).

Two jobs in one command, because they need the same subscription:

1. Capture an option-chain tape that the ANL-03 surface dashboard can replay.
2. Measure the Quote/Full channel's *empirical* instrument ceiling. Dhan's documented
   5,000 was disproved for the 20-level depth channel on 2026-08-19 (real ceiling: 50 per
   subscription message), so this command reports, per requested instrument, whether any
   packet ever arrived — the ceiling is read off that coverage, never assumed.

This command never places, modifies, or influences an order.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from shaurya.contracts.data import DataChannel, DatasetRequest
from shaurya.contracts.instruments import DhanInstrumentMaster
from shaurya.contracts.tape import TapeRow
from shaurya.contracts.timing import IST
from shaurya.data.access import (
    DataCaptureSession,
    DataCatalog,
    DatasetAlreadyActiveError,
)
from shaurya.data.dhan_client import DhanCredentials
from shaurya.data.dhan_stream import DhanLiveStream, DhanStreamConfig, StreamMetrics
from shaurya.data.storage import resolve_data_catalog, resolve_raw_capture_root
from shaurya.data.universe import select_chain_universe


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", required=True, type=Path)
    parser.add_argument("--security-master", required=True, type=Path)
    parser.add_argument(
        "--underlying",
        action="append",
        default=None,
        help="Repeat to probe a universe wider than one underlying can supply.",
    )
    parser.add_argument(
        "--expiry",
        action="append",
        required=True,
        help="ISO expiry date; repeat for several maturities.",
    )
    parser.add_argument("--spot", required=True, type=float)
    parser.add_argument("--strike-window-fraction", type=float, default=0.06)
    parser.add_argument("--max-options", type=int, default=120)
    parser.add_argument("--duration-seconds", type=float, default=120.0)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help=(
            "Override the capture root for a controlled test. By default DAT writes to "
            "/Volumes/Aryan/NSE/YYYY-MM-DD/raw after verifying the SMB mount."
        ),
    )
    parser.add_argument(
        "--allow-nonarchive-output",
        action="store_true",
        help="Permit an intentional isolated test capture outside the configured NSE archive.",
    )
    parser.add_argument(
        "--data-catalog",
        type=Path,
        default=None,
    )
    parser.add_argument("--archive-on-close", action="store_true")
    parser.add_argument("--heartbeat-interval-seconds", type=float, default=10.0)
    parser.add_argument("--heartbeat-timeout-seconds", type=float, default=5.0)
    return parser


def _exclusive_json(path: Path, value: dict[str, Any]) -> None:
    encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


async def _capture(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    if args.duration_seconds <= 0:
        raise ValueError("duration-seconds must be positive")
    master = DhanInstrumentMaster(args.security_master)
    underlyings = args.underlying or ["NIFTY"]
    mappings = list(master.mappings())
    universes = [
        select_chain_universe(
            mappings,
            underlying=underlying,
            expiries=[date.fromisoformat(value) for value in args.expiry],
            spot_reference=args.spot,
            strike_window_fraction=args.strike_window_fraction,
            max_options=args.max_options,
        )
        for underlying in underlyings
    ]
    instruments: list[Any] = []
    seen_ids: set[str] = set()
    for universe in universes:
        for mapping in universe.instruments:
            if mapping.security_id in seen_ids:
                continue
            seen_ids.add(mapping.security_id)
            instruments.append(mapping)
    if not instruments:
        raise ValueError("the requested universe selected no instruments")

    trading_date = instruments[0].as_of_date
    output_root = resolve_raw_capture_root(
        args.output_root,
        trading_date=trading_date,
        allow_nonarchive=args.allow_nonarchive_output,
    )
    catalog_path = resolve_data_catalog(
        args.data_catalog,
        trading_date=trading_date,
        allow_nonarchive=args.allow_nonarchive_output,
        nonarchive_capture_root=output_root,
    )
    credentials = DhanCredentials.from_env_file(args.credentials)

    metrics = StreamMetrics()
    request = DatasetRequest(
        consumer="DAT-chain-capture",
        purpose="shared option-chain Standard/Full capture",
        trading_date=trading_date,
        channels=(DataChannel.STANDARD,),
        instrument_ids=tuple(item.instrument.canonical for item in instruments),
        allow_active=True,
    )
    session = DataCaptureSession.create(
        catalog=DataCatalog(catalog_path),
        request=request,
        output_root=output_root,
        fsync_every=200,
    )
    manifest = session.manifest
    writer = session.writer
    seen: Counter[str] = Counter()
    first_seen: dict[str, str] = {}

    def consume(row: TapeRow) -> None:
        session.write(row)
        seen[row.instrument_id] += 1
        first_seen.setdefault(row.instrument_id, row.receive_ts.astimezone(IST).isoformat())

    config = DhanStreamConfig(
        enable_standard_feed=True,
        enable_20_level_depth=False,
        enable_200_level_depth=False,
        heartbeat_interval_seconds=args.heartbeat_interval_seconds,
        heartbeat_timeout_seconds=args.heartbeat_timeout_seconds,
    )
    stream = DhanLiveStream(
        credentials,
        instruments,
        consume,
        run_id=str(manifest.run_id),
        config=config,
        metrics=metrics,
    )
    started = time.monotonic()
    stream_error: BaseException | None = None
    task = asyncio.create_task(stream.run())
    done, _ = await asyncio.wait({task}, timeout=args.duration_seconds)
    elapsed = time.monotonic() - started
    if task not in done:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    else:
        try:
            task.result()
            stream_error = RuntimeError("Dhan stream ended unexpectedly")
        except BaseException as exc:  # noqa: BLE001 - recorded, then reported
            stream_error = exc
    requested = [mapping.instrument.canonical for mapping in instruments]
    covered = [name for name in requested if seen[name] > 0]
    silent = [name for name in requested if seen[name] == 0]
    report: dict[str, Any] = {
        "run_id": str(manifest.run_id),
        "dataset_id": session.dataset_id,
        "generated_at": datetime.now(tz=IST).isoformat(),
        "channel": "standard_quote_full_request_code_21",
        "subscription_batch_size": 100,
        "elapsed_seconds": elapsed,
        "universes": [item.to_dict() for item in universes],
        "requested_instruments": len(requested),
        "instruments_with_packets": len(covered),
        "instruments_without_packets": len(silent),
        "first_silent_request_index": (
            requested.index(silent[0]) if silent else None
        ),
        "silent_instruments": silent,
        "rows": metrics.rows,
        "reconnect_attempts": dict(metrics.reconnect_attempts),
        "connections": dict(metrics.connections),
        "heartbeat_timeouts": dict(metrics.heartbeat_timeouts),
        "packets_per_instrument": dict(seen),
        "first_packet_ist_per_instrument": first_seen,
        "stream_error": type(stream_error).__name__ if stream_error else None,
        "tape_path": str(writer.path),
    }
    coverage_path = manifest.run_dir / "chain_coverage.json"
    _exclusive_json(coverage_path, report)
    manifest.register_existing(coverage_path, kind="chain_coverage")
    reason = (
        f"stream failed: {type(stream_error).__name__}"
        if stream_error is not None
        else "capture interval produced zero covered instruments"
        if not covered
        else None
    )
    handle = session.close(
        invalidation_reason=reason,
        archive=args.archive_on_close,
    )
    report["dataset_handle"] = handle.model_dump(mode="json")
    return (0 if covered else 1), report


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        code, report = asyncio.run(_capture(args))
    except DatasetAlreadyActiveError as exc:
        code = 0
        report = {
            "status": "reused_active_dataset",
            "dataset_handle": exc.handle.model_dump(mode="json"),
        }
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
