"""ANL-03: serve the live implied-volatility surface dashboard.

Two drive modes over one engine and one dashboard:

* ``replay`` — DAT-05 replay of a retained tape. Fits run in tape time, so a ten-minute tape
  reproduces a ten-minute session deterministically.
* ``live`` — exactly one Dhan Quote/Full connection.

The process is read-only in both modes: it subscribes, fits, and serves HTTP. It imports no
order path and holds no broker write credential beyond the same read token the capture CLI
uses (D19).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from shaurya.analytics.server import DashboardState, serve_in_background
from shaurya.analytics.surface_feed import (
    StalenessPolicy,
    SurfaceEngine,
    default_log_moneyness_grid,
)
from shaurya.analytics.universe import select_chain_universe
from shaurya.contracts.artifacts import ArtifactManifest
from shaurya.contracts.instruments import DhanInstrumentMaster
from shaurya.contracts.tape import TapeRow
from shaurya.contracts.timing import IST
from shaurya.data.dhan_client import DhanCredentials
from shaurya.data.dhan_stream import DhanLiveStream, DhanStreamConfig, StreamMetrics
from shaurya.data.tape import JsonlTapeReader, JsonlTapeWriter

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("replay", "live"), required=True)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--expiry", action="append", required=True)
    parser.add_argument("--fit-interval-seconds", type=float, default=5.0)
    parser.add_argument("--surface-staleness-seconds", type=float, default=60.0)
    parser.add_argument("--fit-stale-seconds", type=float, default=20.0)
    parser.add_argument(
        "--post-stream-seconds",
        type=float,
        default=0.0,
        help="live mode: keep serving after the stream stops, so feed death is observable.",
    )
    parser.add_argument("--feed-slow-seconds", type=float, default=1.0)
    parser.add_argument("--feed-dead-seconds", type=float, default=2.0)
    parser.add_argument("--moneyness-half-width", type=float, default=0.08)
    parser.add_argument("--moneyness-points", type=int, default=33)
    parser.add_argument("--min-quotes-per-slice", type=int, default=5)
    parser.add_argument("--risk-free-rate", type=float, default=0.0)
    parser.add_argument("--serve-seconds", type=float, default=0.0,
                        help="Stop after this many seconds; 0 serves until interrupted.")
    # replay
    parser.add_argument("--tape", type=Path, help="replay mode: canonical JSONL tape")
    parser.add_argument("--replay-speed", type=float, default=0.0,
                        help="replay mode: 0 replays as fast as possible, 1.0 is real time")
    # live
    parser.add_argument("--credentials", type=Path)
    parser.add_argument("--security-master", type=Path)
    parser.add_argument("--underlying", default="NIFTY")
    parser.add_argument("--spot", type=float)
    parser.add_argument("--strike-window-fraction", type=float, default=0.06)
    parser.add_argument("--max-options", type=int, default=120)
    parser.add_argument("--output-root", type=Path,
                        default=Path("data/live-captures/anl03-live"))
    return parser


def _engine(args: argparse.Namespace, run_id: str, source: str) -> SurfaceEngine:
    policy = StalenessPolicy(
        feed_slow_seconds=args.feed_slow_seconds,
        feed_dead_seconds=args.feed_dead_seconds,
        surface_staleness_seconds=args.surface_staleness_seconds,
        fit_stale_seconds=args.fit_stale_seconds,
    )
    return SurfaceEngine(
        run_id=run_id,
        surface_id=f"anl03-{source}",
        expiries=tuple(date.fromisoformat(value) for value in args.expiry),
        log_moneyness_grid=default_log_moneyness_grid(
            half_width=args.moneyness_half_width, points=args.moneyness_points
        ),
        policy=policy,
        fit_interval_seconds=args.fit_interval_seconds,
        risk_free_rate=args.risk_free_rate,
        min_quotes_per_slice=args.min_quotes_per_slice,
        wall_clock=source == "live",
    )


def _summarise(engine: SurfaceEngine) -> dict[str, Any]:
    history = engine.history
    fits = [snapshot for snapshot in history if snapshot.fit_ok]
    failures = [snapshot for snapshot in history if not snapshot.fit_ok]
    durations = sorted(snapshot.fit_duration_seconds for snapshot in fits)
    ages = sorted(
        snapshot.health.feed_age_seconds
        for snapshot in history
        if snapshot.health.feed_age_seconds is not None
    )

    def quantile(values: list[float], fraction: float) -> float | None:
        if not values:
            return None
        index = min(len(values) - 1, max(0, round(fraction * (len(values) - 1))))
        return values[index]

    surface_ages = sorted(
        snapshot.surface_age_seconds
        for snapshot in fits
        if snapshot.surface_age_seconds is not None
    )
    smoothing_states: set[str] = set()
    for snapshot in fits:
        state = snapshot.diagnostics.get("temporal_smoothing")
        status = state.get("status") if isinstance(state, dict) else None
        smoothing_states.add(str(status).split(":")[0])
    arbitrage_failures = [
        snapshot.sequence
        for snapshot in fits
        if snapshot.arbitrage is not None and not snapshot.arbitrage.get("passed")
    ]
    return {
        "snapshots": len(history),
        "fits_ok": len(fits),
        "fits_failed": len(failures),
        "failure_reasons": sorted({str(item.failure_reason) for item in failures}),
        "fit_duration_p50": quantile(durations, 0.5),
        "fit_duration_p95": quantile(durations, 0.95),
        "fit_duration_max": durations[-1] if durations else None,
        "feed_age_p50": quantile(ages, 0.5),
        "feed_age_p95": quantile(ages, 0.95),
        "feed_age_max": ages[-1] if ages else None,
        "surface_age_p50": quantile(surface_ages, 0.5),
        "surface_age_p95": quantile(surface_ages, 0.95),
        "surface_age_max": surface_ages[-1] if surface_ages else None,
        "temporal_smoothing_states": sorted(smoothing_states),
        "arbitrage_failing_snapshots": arbitrage_failures,
        "instruments_tracked": (
            history[-1].health.tracked_instrument_count if history else 0
        ),
        "reconnects": history[-1].health.reconnect_count if history else 0,
    }


def _run_replay(args: argparse.Namespace) -> dict[str, Any]:
    if args.tape is None:
        raise SystemExit("replay mode requires --tape")
    reader = JsonlTapeReader(args.tape)
    engine = _engine(args, run_id=args.tape.stem, source="replay")
    state = DashboardState(
        engine,
        title="Shaurya ANL-03 — implied volatility surface (REPLAY)",
        source=f"replay {args.tape.name}",
    )
    server, _ = serve_in_background(state, host=args.host, port=args.port)
    print(f"ANL-03 dashboard serving at http://{args.host}:{args.port}/", flush=True)
    started_wall = time.monotonic()
    first_tape: datetime | None = None
    try:
        for row in reader.rows():
            stamp = row.receive_ts.astimezone(IST)
            if first_tape is None:
                first_tape = stamp
            if args.replay_speed > 0:
                target = (stamp - first_tape).total_seconds() / args.replay_speed
                drift = target - (time.monotonic() - started_wall)
                if drift > 0:
                    time.sleep(drift)
            engine.ingest(row)
            if engine.due_for_fit(stamp):
                engine.fit(stamp)
        if args.serve_seconds > 0:
            print(
                f"replay exhausted; serving the final state for {args.serve_seconds:.0f}s",
                flush=True,
            )
            time.sleep(args.serve_seconds)
    finally:
        server.shutdown()
    return _summarise(engine)


async def _run_live(args: argparse.Namespace) -> dict[str, Any]:
    missing = [
        name
        for name in ("credentials", "security_master", "spot")
        if getattr(args, name) is None
    ]
    if missing:
        raise SystemExit(f"live mode requires: {', '.join(sorted(missing))}")
    credentials = DhanCredentials.from_env_file(args.credentials)
    master = DhanInstrumentMaster(args.security_master)
    universe = select_chain_universe(
        master.mappings(),
        underlying=args.underlying,
        expiries=[date.fromisoformat(value) for value in args.expiry],
        spot_reference=args.spot,
        strike_window_fraction=args.strike_window_fraction,
        max_options=args.max_options,
    )
    manifest = ArtifactManifest.create(args.output_root)
    writer = JsonlTapeWriter(manifest, fsync_every=200)
    engine = _engine(args, run_id=str(manifest.run_id), source="live")
    state = DashboardState(
        engine,
        title="Shaurya ANL-03 — implied volatility surface (LIVE)",
        source=f"live dhan quote/full · {len(universe.instruments)} instruments",
    )
    server, _ = serve_in_background(state, host=args.host, port=args.port)
    print(f"ANL-03 dashboard serving at http://{args.host}:{args.port}/", flush=True)

    lock = threading.Lock()

    def consume(row: TapeRow) -> None:
        writer.write(row)
        with lock:
            engine.ingest(row)

    async def fit_loop() -> None:
        while True:
            await asyncio.sleep(min(1.0, args.fit_interval_seconds))
            now = datetime.now(tz=IST)
            with lock:
                if engine.due_for_fit(now):
                    engine.fit(now)

    stream = DhanLiveStream(
        credentials,
        list(universe.instruments),
        consume,
        run_id=str(manifest.run_id),
        config=DhanStreamConfig(
            enable_standard_feed=True,
            enable_20_level_depth=False,
            enable_200_level_depth=False,
        ),
        metrics=StreamMetrics(),
    )
    stream_task = asyncio.create_task(stream.run())
    fit_task = asyncio.create_task(fit_loop())
    error: BaseException | None = None
    try:
        if args.serve_seconds > 0:
            await asyncio.wait({stream_task}, timeout=args.serve_seconds)
        else:
            await stream_task
    except BaseException as exc:  # noqa: BLE001 - reported in the summary
        error = exc
    finally:
        for task in (stream_task, fit_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(stream_task, fit_task, return_exceptions=True)
        writer.close(failed_error_type=type(error).__name__ if error else None)
        if args.post_stream_seconds > 0:
            print(
                "stream stopped; serving for "
                f"{args.post_stream_seconds:.0f}s so feed death is observable",
                flush=True,
            )
            await asyncio.sleep(args.post_stream_seconds)
            summary_health = engine.sample_health(datetime.now(tz=IST))
            print(json.dumps({"post_stream_health": summary_health.to_dict()}), flush=True)
        server.shutdown()
    summary = _summarise(engine)
    summary["universe"] = universe.to_dict()
    summary["tape_path"] = str(writer.path)
    summary["stream_error"] = type(error).__name__ if error else None
    return summary


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    summary = (
        _run_replay(args) if args.mode == "replay" else asyncio.run(_run_live(args))
    )
    json.dump(summary, sys.stdout, indent=2, sort_keys=True, default=str)
    sys.stdout.write("\n")
    return 0 if summary["fits_ok"] else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
