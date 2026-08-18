"""Read-only Dhan live capture CLI for DAT-02 validation and collection."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from shaurya.contracts.artifacts import ArtifactManifest
from shaurya.contracts.instruments import DhanInstrumentMaster
from shaurya.data.dhan_client import DhanCredentials
from shaurya.data.dhan_stream import DhanLiveStream, DhanStreamConfig, StreamMetrics
from shaurya.data.tape import JsonlTapeWriter


def _exclusive_json(path: Path, value: dict[str, Any]) -> None:
    encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", required=True, type=Path)
    parser.add_argument("--security-master", required=True, type=Path)
    parser.add_argument("--security-id", required=True)
    parser.add_argument(
        "--expected-symbol",
        required=True,
        help="Safety check: capture aborts unless the master maps the ID to this exact symbol.",
    )
    parser.add_argument("--duration-seconds", type=float, default=180.0)
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/dhan-live"))
    parser.add_argument("--no-standard", action="store_true")
    parser.add_argument("--no-depth20", action="store_true")
    parser.add_argument(
        "--enable-depth200",
        action="store_true",
        help="DAT-10: opt-in 200-level deep book. Dhan allows exactly one instrument per "
        "subscription on this endpoint, which --security-id already satisfies.",
    )
    parser.add_argument("--heartbeat-interval-seconds", type=float, default=10.0)
    parser.add_argument("--heartbeat-timeout-seconds", type=float, default=5.0)
    return parser


def _required_channels(config: DhanStreamConfig) -> set[str]:
    required: set[str] = set()
    if config.enable_standard_feed:
        required.add("standard")
    if config.enable_20_level_depth:
        required.add("depth20")
    if config.enable_200_level_depth:
        required.add("depth200")
    return required


async def _capture(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    if args.duration_seconds <= 0:
        raise ValueError("duration-seconds must be positive")
    credentials = DhanCredentials.from_env_file(args.credentials)
    mapping = DhanInstrumentMaster(args.security_master).find_by_security_id(args.security_id)
    if mapping.trading_symbol != args.expected_symbol:
        raise ValueError(
            f"security-ID identity check failed: expected {args.expected_symbol!r}, "
            f"master has {mapping.trading_symbol!r}"
        )
    manifest = ArtifactManifest.create(args.output_root)
    metrics = StreamMetrics()
    writer = JsonlTapeWriter(manifest, fsync_every=100)
    config = DhanStreamConfig(
        enable_standard_feed=not args.no_standard,
        enable_20_level_depth=not args.no_depth20,
        enable_200_level_depth=args.enable_depth200,
        heartbeat_interval_seconds=args.heartbeat_interval_seconds,
        heartbeat_timeout_seconds=args.heartbeat_timeout_seconds,
    )
    stream = DhanLiveStream(
        credentials,
        [mapping],
        writer.write,
        run_id=str(manifest.run_id),
        config=config,
        metrics=metrics,
    )
    started = time.monotonic()
    capture_elapsed: float | None = None
    stream_error: BaseException | None = None
    task = asyncio.create_task(stream.run())
    done, _ = await asyncio.wait({task}, timeout=args.duration_seconds)
    capture_elapsed = time.monotonic() - started
    if task not in done:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    else:
        try:
            task.result()
            stream_error = RuntimeError("Dhan stream ended unexpectedly")
        except BaseException as exc:
            stream_error = exc
    total_elapsed = time.monotonic() - started
    writer.close(failed_error_type=type(stream_error).__name__ if stream_error else None)
    snapshot = metrics.snapshot(capture_elapsed)
    snapshot["shutdown_seconds"] = max(total_elapsed - capture_elapsed, 0.0)
    required_channels = _required_channels(config)
    missing_channels = sorted(
        channel for channel in required_channels if metrics.source_packets[channel] == 0
    )
    snapshot.update(
        {
            "run_id": str(manifest.run_id),
            "instrument_id": mapping.instrument.canonical,
            "dhan_security_id": mapping.security_id,
            "trading_symbol": mapping.trading_symbol,
            "test_configuration": {
                "standard_full_5_level": not args.no_standard,
                "depth20": not args.no_depth20,
                "depth200": args.enable_depth200,
                "duration_seconds_requested": args.duration_seconds,
                "dat09_decision": False,
            },
            "stream_error_type": type(stream_error).__name__ if stream_error else None,
            "acceptance": {
                "required_channels": sorted(required_channels),
                "missing_channels": missing_channels,
            },
        }
    )
    metrics_path = manifest.run_dir / f"capture_metrics_{manifest.run_id}.json"
    _exclusive_json(metrics_path, snapshot)
    manifest.register_existing(metrics_path, kind="capture_metrics")
    if stream_error:
        manifest.invalidate(f"stream failed: {type(stream_error).__name__}")
        return 2, {**snapshot, "run_dir": str(manifest.run_dir), "status": "invalidated"}
    if writer.rows_written == 0:
        manifest.invalidate("capture interval produced zero normalized rows")
        return 3, {**snapshot, "run_dir": str(manifest.run_dir), "status": "invalidated"}
    if missing_channels:
        manifest.invalidate(
            "enabled channels produced zero source packets: " + ",".join(missing_channels)
        )
        return 4, {**snapshot, "run_dir": str(manifest.run_dir), "status": "invalidated"}
    manifest.complete(rows=writer.rows_written, elapsed_seconds=capture_elapsed)
    return 0, {**snapshot, "run_dir": str(manifest.run_dir), "status": "completed"}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        code, summary = asyncio.run(_capture(args))
    except BaseException as exc:
        # Never print exception text: an upstream networking exception may contain an auth URL.
        print(
            json.dumps({"status": "preflight_failed", "error_type": type(exc).__name__}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(summary, sort_keys=True, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
